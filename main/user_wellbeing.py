"""
ユーザーの気分（発話の感情傾向）を観測し、アバターが寄り添う一言を返すモジュール。

`mood.py` がアバターの「好感度（関係の深さ）」を扱うのに対し、本モジュールは
**ユーザー自身が最近どんな気分か**を会話ログの発話から推定する。最近の発話が
否定的に偏っていれば気づかってそっと声をかけ、明るければ一緒に喜ぶ——という
「気分の寄り添い」を提供する。

設計方針:
- LLM・外部 API 非依存。感情極性は mood.classify_sentiment（既存の感情語）を再利用。
- 会話ログ（avatar_event_log.jsonl）の **ユーザー発話のみ**を対象に集計する。
- 判定はデータ不足・中立では何も言わない（過剰な押し付けを避ける）。
- メッセージは設定不要で動く組み込み既定を持ち、直前と重複しない無作為選択。

主な公開 API:
  wellbeing_summary(event_log_path=None, days=3, now=None) -> dict
  wellbeing_message(summary, lang="ja") -> str
  wellbeing_reflection(event_log_path=None, days=3, lang="ja", now=None) -> str
"""
from __future__ import annotations

import os
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

logger_name = __name__

# 感情分類は mood を唯一の真実の源として再利用（防御的フォールバック付き）。
try:
    from mood import classify_sentiment as _classify_sentiment
except Exception:  # pragma: no cover - defensive fallback
    def _classify_sentiment(text: str) -> int:
        return 0

# ユーザー発話の判定に必要な会話ログの分類とパス。
try:
    from conversation_log import USER_EVENT_TYPES as _USER_EVENT_TYPES
    from conversation_log import DEFAULT_LOGFILE as _DEFAULT_LOGFILE
    from conversation_log import _find_archives
except Exception:  # pragma: no cover - defensive fallback
    _USER_EVENT_TYPES = frozenset({"user_comment", "user"})
    _DEFAULT_LOGFILE = "avatar_event_log.jsonl"
    # 引数名は本物（conversation_log._find_archives）と一致させる。ずれていると
    # キーワード呼び出しがフォールバック時だけ TypeError になる。
    def _find_archives(logfile: str) -> List[str]:
        return []

try:
    from fsutil import load_jsonl_dicts as _load_jsonl_dicts
except Exception:  # pragma: no cover - defensive fallback
    def _load_jsonl_dicts(path: str, *, encoding: str = "utf-8") -> List[Dict]:
        import json
        if not os.path.exists(path):
            return []
        out: List[Dict] = []
        try:
            with open(path, encoding=encoding) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        out.append(obj)
        except OSError:
            return []
        return out


def _load_jsonl_with_archives(path: str) -> List[Dict]:
    """ライブ JSONL に加え、ローテート済み .gz アーカイブも読み込む。

    wellbeing_summary は既定 days=3 と複数日にまたがって集計するが、
    以前は _load_jsonl_dicts(path) でライブファイルしか読んでおらず、
    avatar_event_log_rotate.rotate_log() によるサイズローテーションを
    挟むとローテート済みアーカイブ内のユーザー発話が集計から消えていた
    （daily_summary.py の _load_jsonl(include_archives=True) が既に
    同じ問題を解決済みの箇所であり、同じパターンをここでも適用する）。
    """
    entries: List[Dict] = list(_load_jsonl_dicts(path))
    for gz_path in _find_archives(path):
        try:
            import gzip
            import json
            with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        entries.append(obj)
        except Exception:  # pragma: no cover - defensive
            continue
    return entries


# 判定に必要な最低発話数。少なすぎると偶然に振り回されるため何も言わない。
_MIN_SAMPLE = 3
# 「低調 / 上向き」と断ずるのに必要な、優勢側の最低件数。
_MIN_DOMINANT = 2

# ------------------------------------------------------------------
# 変化点検知（研究 A5）: 絶対的な「低調/上向き」ではなく、ユーザー自身の
# 直近の基準からの**変化**を捉える。普段は明るい人が数日だけ落ち込んだ場合、
# 絶対値では「否定優勢」に届かなくても、基準比の低下として気づける。
# 重い BOCPD (arXiv:0710.3742) の代わりに、直近窓と基準窓の平均感情スコアを
# 比較する軽量・決定論的なプロキシを用いる（LLM/重依存なし）。
# ------------------------------------------------------------------
_SHIFT_RECENT_DAYS = 2       # 直近窓（今日と昨日）
_SHIFT_BASELINE_DAYS = 7     # 直近窓の直前の基準窓（7日）
_SHIFT_MIN_RECENT = 3        # 直近窓に必要な最低サンプル数
_SHIFT_MIN_BASELINE = 5      # 基準窓に必要な最低サンプル数（無ければ変化と断じない）
_SHIFT_MIN_DELTA = 0.5       # 平均スコア差がこの絶対値以上で「変化あり」

# 寄り添いメッセージ（組み込み既定）。trend → lang → 候補。
_WELLBEING_MESSAGES: Dict[str, Dict[str, List[str]]] = {
    "low": {
        "ja": [
            "最近、少し元気がないみたいだね。無理しないで、いつでも話してね。",
            "ここのところ大変そう…。あなたの味方だからね。",
            "ちょっと疲れてるのかな？ゆっくり休むのも大事だよ。",
        ],
        "en": [
            "You've seemed a little down lately. Don't push yourself — I'm always here.",
            "Things have felt heavy for you recently. I'm on your side, you know.",
            "Maybe you're worn out? It's okay to rest and take it slow.",
        ],
    },
    "high": {
        "ja": [
            "最近すごく楽しそう！見ているこっちまでうれしくなるよ。",
            "ここのところ調子よさそうだね。その笑顔、大好きだよ。",
            "いい感じの毎日みたいで、わたしもうれしいな！",
        ],
        "en": [
            "You've sounded really cheerful lately! It makes me happy too.",
            "You seem to be doing great recently. I love that energy.",
            "Your days sound good lately — that makes me glad!",
        ],
    },
}


# wellbeing_summary の結果を 60 秒キャッシュする（大きなログファイルの再読を防ぐ）。
# テスト用に now= を明示した場合はキャッシュをバイパスして決定論的挙動を維持する。
_SUMMARY_CACHE_TTL = 60.0
_summary_cache: Dict[Tuple[str, int], Tuple[Dict, float]] = {}
_summary_cache_lock = threading.Lock()

# _last_pick への同時アクセスを保護する（複数スレッドから wellbeing_message が呼ばれる場合）。
_last_pick_lock = threading.Lock()


def _lang_key(lang: Optional[str]) -> str:
    """言語コードを 'ja' / 'en' のいずれかへ正規化する（未知は en）。"""
    s = str(lang or "").lower()
    return "ja" if s.startswith("ja") else "en"


def _start_of_day(ts: float) -> float:
    """ts を含む「日」の 0:00 のローカル Unix タイムスタンプを返す。"""
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def wellbeing_summary(
    event_log_path: Optional[str] = None,
    days: int = 3,
    now: Optional[float] = None,
) -> Dict:
    """直近 days 日のユーザー発話の感情傾向を集計して返す。

    Returns dict:
        {
          "sample_size": int,   # 集計対象となったユーザー発話数
          "positive": int,
          "negative": int,
          "neutral": int,
          "score": int,         # positive - negative
          "trend": "low" | "high" | "neutral",
        }

    trend は保守的に決める: サンプルが _MIN_SAMPLE 未満なら "neutral"、
    否定が優勢かつ _MIN_DOMINANT 以上なら "low"、肯定が優勢かつ _MIN_DOMINANT
    以上なら "high"、それ以外は "neutral"。

    now が None（本番用途）のときは結果を _SUMMARY_CACHE_TTL 秒間キャッシュして
    大きなログファイルへの連続読み込みを避ける。now= を明示した場合（テスト）は
    キャッシュをバイパスし、決定論的な挙動を維持する。
    """
    path = event_log_path or _DEFAULT_LOGFILE
    use_cache = now is None
    real_now = time.time() if now is None else now

    if use_cache:
        cache_key = (path, days)
        with _summary_cache_lock:
            cached = _summary_cache.get(cache_key)
        if cached is not None:
            result, cached_at = cached
            if real_now - cached_at < _SUMMARY_CACHE_TTL:
                return result

    # days 日前の 0:00 以降を対象（days=1 なら「今日」だけ）。
    cutoff = _start_of_day(real_now) - max(0, days - 1) * 86400

    pos = neg = neu = 0
    for ev in _load_jsonl_with_archives(path):
        if ev.get("event_type") not in _USER_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if not isinstance(ts, (int, float)) or ts < cutoff or ts > real_now:
            continue
        text = (ev.get("details") or {}).get("text") or ""
        s = _classify_sentiment(text)
        if s > 0:
            pos += 1
        elif s < 0:
            neg += 1
        else:
            neu += 1

    sample = pos + neg + neu
    trend = "neutral"
    if sample >= _MIN_SAMPLE:
        if neg > pos and neg >= _MIN_DOMINANT:
            trend = "low"
        elif pos > neg and pos >= _MIN_DOMINANT:
            trend = "high"

    result = {
        "sample_size": sample,
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "score": pos - neg,
        "trend": trend,
    }
    if use_cache:
        with _summary_cache_lock:
            _summary_cache[(path, days)] = (result, real_now)
    return result


# 直前に選んだメッセージ（連続重複回避用）。trend ごとに保持。
_last_pick: Dict[str, str] = {}


def wellbeing_message(summary: Dict, lang: str = "ja") -> str:
    """集計結果 summary に基づく寄り添いの一言を返す。

    trend が "neutral"（データ不足含む）のときは空文字を返し、呼び出し側が
    「何も言わない」を選べるようにする。直前と同じ文は避ける。
    """
    if not isinstance(summary, dict):
        return ""
    trend = summary.get("trend")
    if trend not in ("low", "high"):
        return ""
    key = _lang_key(lang)
    options = (_WELLBEING_MESSAGES.get(trend, {}).get(key)
               or _WELLBEING_MESSAGES.get(trend, {}).get("en") or [])
    if not options:
        return ""
    with _last_pick_lock:
        last = _last_pick.get(trend)
        choices = [o for o in options if o != last] or options
        pick = random.choice(choices)
        _last_pick[trend] = pick
    return pick


# 変化点メッセージ（組み込み既定）。shift → lang → 候補。
# 「あなた自身の普段と比べての変化」を根拠に、押し付けず気づかう / 一緒に喜ぶ。
_SHIFT_MESSAGES: Dict[str, Dict[str, List[str]]] = {
    "down": {
        "ja": [
            "前より少し元気がないみたいで、気になってるよ。何かあった？無理はしないでね。",
            "いつものあなたと比べて、ちょっと沈んでる気がして…。よかったら話きくよ。",
            "最近ちょっとしんどそうかな。あなたのペースでいいからね。",
        ],
        "en": [
            "You've seemed a bit down compared to your usual self — is everything okay? Don't push yourself.",
            "You feel a little quieter than you normally are lately… I'm here if you want to talk.",
            "Things seem a touch heavier than usual for you. Go at your own pace, okay?",
        ],
    },
    "up": {
        "ja": [
            "最近、前より明るくなった気がする！いいことあったのかな。",
            "このごろ調子上向きだね。見ていてこっちまでうれしくなるよ。",
            "前よりずっと元気そう！その感じ、すてきだよ。",
        ],
        "en": [
            "You've seemed brighter than before lately! Did something good happen?",
            "You're on an upswing recently — it makes me happy just seeing it.",
            "You seem so much more energetic than before! I love that.",
        ],
    },
}


def wellbeing_shift(
    event_log_path: Optional[str] = None,
    now: Optional[float] = None,
    recent_days: int = _SHIFT_RECENT_DAYS,
    baseline_days: int = _SHIFT_BASELINE_DAYS,
) -> Dict:
    """ユーザー自身の基準からの気分の**変化**を検知する（変化点検知）。

    直近 recent_days 日の平均感情スコアと、その直前 baseline_days 日の平均を
    比較し、有意に下がっていれば "down"、上がっていれば "up"、それ以外や
    サンプル不足なら "none" を返す。基準窓に十分なサンプルが無い場合は
    「変化」とは断じない（絶対判定は wellbeing_summary が担当）。

    Returns dict:
        {
          "shift": "down" | "up" | "none",
          "recent_mean": float,
          "baseline_mean": float,
          "recent_samples": int,
          "baseline_samples": int,
        }
    """
    path = event_log_path or _DEFAULT_LOGFILE
    real_now = time.time() if now is None else now

    recent_start = _start_of_day(real_now) - max(0, recent_days - 1) * 86400
    baseline_start = recent_start - max(1, baseline_days) * 86400

    recent_scores: List[int] = []
    baseline_scores: List[int] = []
    for ev in _load_jsonl_with_archives(path):
        if ev.get("event_type") not in _USER_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if not isinstance(ts, (int, float)) or ts > real_now:
            continue
        text = (ev.get("details") or {}).get("text") or ""
        s = _classify_sentiment(text)
        if ts >= recent_start:
            recent_scores.append(s)
        elif ts >= baseline_start:
            baseline_scores.append(s)

    recent_n = len(recent_scores)
    base_n = len(baseline_scores)
    shift = "none"
    recent_mean = 0.0
    base_mean = 0.0
    if recent_n >= _SHIFT_MIN_RECENT and base_n >= _SHIFT_MIN_BASELINE:
        recent_mean = sum(recent_scores) / recent_n
        base_mean = sum(baseline_scores) / base_n
        delta = recent_mean - base_mean
        if delta <= -_SHIFT_MIN_DELTA:
            shift = "down"
        elif delta >= _SHIFT_MIN_DELTA:
            shift = "up"

    return {
        "shift": shift,
        "recent_mean": recent_mean,
        "baseline_mean": base_mean,
        "recent_samples": recent_n,
        "baseline_samples": base_n,
    }


def wellbeing_shift_message(shift_summary: Dict, lang: str = "ja") -> str:
    """変化点検知結果に基づく一言を返す（shift が none/不正なら空文字）。"""
    if not isinstance(shift_summary, dict):
        return ""
    shift = shift_summary.get("shift")
    if shift not in ("down", "up"):
        return ""
    key = _lang_key(lang)
    options = (_SHIFT_MESSAGES.get(shift, {}).get(key)
               or _SHIFT_MESSAGES.get(shift, {}).get("en") or [])
    if not options:
        return ""
    pick_key = f"shift_{shift}"
    with _last_pick_lock:
        last = _last_pick.get(pick_key)
        choices = [o for o in options if o != last] or options
        pick = random.choice(choices)
        _last_pick[pick_key] = pick
    return pick


def wellbeing_reflection(
    event_log_path: Optional[str] = None,
    days: int = 3,
    lang: str = "ja",
    now: Optional[float] = None,
) -> str:
    """寄り添いの一言を返す便利関数（空なら何も言わない）。

    まずユーザー自身の基準からの**変化**（変化点検知）を優先する。基準比の
    変化は、絶対的な低調/上向きよりも気づかいの価値が高く、かつ普段明るい人の
    一時的な落ち込みも捉えられるため。変化が無ければ従来どおり直近 days 日の
    絶対傾向で判断する。
    """
    shift = wellbeing_shift(event_log_path=event_log_path, now=now)
    smsg = wellbeing_shift_message(shift, lang=lang)
    if smsg:
        return smsg
    summary = wellbeing_summary(event_log_path=event_log_path, days=days, now=now)
    return wellbeing_message(summary, lang=lang)
