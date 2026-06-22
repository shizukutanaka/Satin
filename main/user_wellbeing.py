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
import time
from typing import Dict, List, Optional

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
except Exception:  # pragma: no cover - defensive fallback
    _USER_EVENT_TYPES = frozenset({"user_comment", "user"})
    _DEFAULT_LOGFILE = "avatar_event_log.jsonl"

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


# 判定に必要な最低発話数。少なすぎると偶然に振り回されるため何も言わない。
_MIN_SAMPLE = 3
# 「低調 / 上向き」と断ずるのに必要な、優勢側の最低件数。
_MIN_DOMINANT = 2

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
    """
    path = event_log_path or _DEFAULT_LOGFILE
    now = time.time() if now is None else now
    # days 日前の 0:00 以降を対象（days=1 なら「今日」だけ）。
    cutoff = _start_of_day(now) - max(0, days - 1) * 86400

    pos = neg = neu = 0
    for ev in _load_jsonl_dicts(path):
        if ev.get("event_type") not in _USER_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if not isinstance(ts, (int, float)) or ts < cutoff or ts > now:
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

    return {
        "sample_size": sample,
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "score": pos - neg,
        "trend": trend,
    }


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
    last = _last_pick.get(trend)
    choices = [o for o in options if o != last] or options
    pick = random.choice(choices)
    _last_pick[trend] = pick
    return pick


def wellbeing_reflection(
    event_log_path: Optional[str] = None,
    days: int = 3,
    lang: str = "ja",
    now: Optional[float] = None,
) -> str:
    """集計から寄り添いの一言までを一括で行う便利関数（空なら何も言わない）。"""
    summary = wellbeing_summary(event_log_path=event_log_path, days=days, now=now)
    return wellbeing_message(summary, lang=lang)
