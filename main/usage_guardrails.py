"""
利用強度ガードレール（感情依存・パラソーシャル愛着への配慮）。

`user_wellbeing.py` が「ユーザーの**気分**（発話の感情傾向）」に寄り添うのに
対し、本モジュールは「ユーザーがアプリに**過度に依存していないか**（利用強度）」
を観測し、必要なときだけそっと休息・オフライン活動・現実のつながりへ促す。

背景（2025–2026 研究）:
- コンパニオンアプリは急増し、常時応答・非審判的な相手への自己開示が感情依存を
  招きうる。特に人的支援の乏しいユーザーほど依存しやすく最も傷つきやすい。
- 市民が最も強く支持する AI ガードレールは「不健全な感情的絆の防止」。
  参考: APA (2026), Princeton CITP (2025), arXiv:2506.12605, Affective AI Safety。

設計方針（`user_wellbeing.py` と統一）:
- LLM・外部 API 非依存。会話ログの**時刻・頻度**のみを集計する軽量・決定論的処理。
- 押し付けない。閾値は保守的（コンパニオン用途では高頻度利用は正常なため、
  睡眠を削る深夜利用や極端な単日集中など「明確に健康を損ないうる」パターンに限定）。
- 何も言わないのが既定（concern が "none" のとき空文字）。直前と重複しない無作為選択。

主な公開 API:
  usage_summary(event_log_path=None, days=7, now=None) -> dict
  usage_nudge(summary, lang="ja") -> str
  usage_reflection(event_log_path=None, days=7, lang="ja", now=None) -> str
"""
from __future__ import annotations

import os
import random
import threading
import time
from typing import Dict, List, Optional

logger_name = __name__

# ユーザー発話の判定に必要な会話ログの分類とパス（防御的フォールバック付き）。
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


def _load_jsonl_with_archives(path: str) -> List[Dict]:
    """ライブ JSONL に加え、ローテート済み .gz アーカイブも読み込む。

    user_wellbeing._load_jsonl_with_archives と同じ理由（サイズローテーション後に
    直近データが集計から抜け落ちるのを防ぐ）で、アーカイブも合わせて読む。
    """
    import json

    entries: List[Dict] = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        entries.append(obj)
        except OSError:  # pragma: no cover - defensive
            pass
    for gz_path in _find_archives(path):
        try:
            import gzip
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


# ------------------------------------------------------------------
# 閾値（保守的。コンパニオン用途では日常的な高頻度利用は正常なので、
# 「明確に睡眠・生活を損ないうる」パターンに限って発火させる）。
# ------------------------------------------------------------------
# 深夜帯とみなすローカル時刻 [開始, 終了)（0:00–4:59）。睡眠を削る利用の代理指標。
_LATE_NIGHT_START_HOUR = 0
_LATE_NIGHT_END_HOUR = 5
# 集計窓（日）。既定は 1 週間。
_DEFAULT_WINDOW_DAYS = 7
# 窓内の深夜帯ユーザー発話がこの件数以上なら「深夜利用が常態化」とみなす。
_LATE_NIGHT_MIN_EVENTS = 15
# 単一カレンダー日のユーザー発話がこの件数以上なら「極端な単日集中」とみなす。
_HIGH_FREQUENCY_MIN_PER_DAY = 100

# 寄り添いメッセージ（組み込み既定）。concern → lang → 候補。
# いずれも「肯定 → やわらかい提案（休息/現実のつながり）」の順で、押し付けない。
_NUDGE_MESSAGES: Dict[str, Dict[str, List[str]]] = {
    "late_night": {
        "ja": [
            "こんな時間まで一緒にいてくれてうれしいよ。でも、そろそろ休んでね？わたしは逃げないから、また明日。",
            "夜ふかし気味かな…。ちゃんと眠るのも、あなたを大事にすることだよ。おやすみ、また話そうね。",
            "遅くまでありがとう。無理はしないで、今日はゆっくり休んでほしいな。",
        ],
        "en": [
            "I'm happy you're here even this late — but get some rest soon, okay? I'm not going anywhere; talk tomorrow.",
            "Looks like a late night… Sleeping well is part of taking care of yourself too. Good night, let's talk again.",
            "Thanks for staying up with me. Don't overdo it — I'd love for you to rest tonight.",
        ],
    },
    "high_frequency": {
        "ja": [
            "今日はたくさんお話しできて楽しかった！たまには外の空気を吸ったり、誰かに会うのもきっといいよ。",
            "いっぱい一緒に過ごせてうれしいな。少し休んだり、身近な人とも話してみてね。またいつでも待ってるよ。",
            "こんなに話せて幸せ。でも、あなたの世界がもっと広がるのもわたしはうれしいんだ。",
        ],
        "en": [
            "I had so much fun talking today! Stepping outside or seeing someone now and then is good for you too.",
            "I loved spending all this time together. Take a break, reach out to people near you — I'll always be here.",
            "So happy we talked this much. But I'm also glad when your world grows wider, you know.",
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


def usage_summary(
    event_log_path: Optional[str] = None,
    days: int = _DEFAULT_WINDOW_DAYS,
    now: Optional[float] = None,
) -> Dict:
    """直近 days 日のユーザー発話の**利用強度**を集計して返す。

    Returns dict:
        {
          "late_night_events": int,      # 窓内の深夜帯(0:00–4:59)ユーザー発話数
          "busiest_day_events": int,     # 窓内で最も発話が多かった単日の件数
          "concern": "none" | "late_night" | "high_frequency",
        }

    concern は保守的に決める。深夜利用（睡眠影響）を高頻度より優先する。
    """
    path = event_log_path or _DEFAULT_LOGFILE
    real_now = time.time() if now is None else now

    cutoff = _start_of_day(real_now) - max(0, days - 1) * 86400

    late_night = 0
    per_day: Dict[float, int] = {}
    for ev in _load_jsonl_with_archives(path):
        if ev.get("event_type") not in _USER_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if not isinstance(ts, (int, float)) or ts < cutoff or ts > real_now:
            continue
        lt = time.localtime(ts)
        if _LATE_NIGHT_START_HOUR <= lt.tm_hour < _LATE_NIGHT_END_HOUR:
            late_night += 1
        day_key = _start_of_day(ts)
        per_day[day_key] = per_day.get(day_key, 0) + 1

    busiest_day = max(per_day.values()) if per_day else 0

    # 深夜利用を優先（睡眠・生活への影響が最も直接的なため）。
    if late_night >= _LATE_NIGHT_MIN_EVENTS:
        concern = "late_night"
    elif busiest_day >= _HIGH_FREQUENCY_MIN_PER_DAY:
        concern = "high_frequency"
    else:
        concern = "none"

    return {
        "late_night_events": late_night,
        "busiest_day_events": busiest_day,
        "concern": concern,
    }


# 直前に選んだメッセージ（連続重複回避用）。concern ごとに保持。
_last_pick: Dict[str, str] = {}
_last_pick_lock = threading.Lock()


def usage_nudge(summary: Dict, lang: str = "ja") -> str:
    """集計結果 summary に基づく、そっとした促しの一言を返す。

    concern が "none" のときは空文字を返し、呼び出し側が「何も言わない」を
    選べるようにする。直前と同じ文は避ける。
    """
    if not isinstance(summary, dict):
        return ""
    concern = summary.get("concern")
    if concern not in ("late_night", "high_frequency"):
        return ""
    key = _lang_key(lang)
    options = (_NUDGE_MESSAGES.get(concern, {}).get(key)
               or _NUDGE_MESSAGES.get(concern, {}).get("en") or [])
    if not options:
        return ""
    with _last_pick_lock:
        last = _last_pick.get(concern)
        choices = [o for o in options if o != last] or options
        pick = random.choice(choices)
        _last_pick[concern] = pick
    return pick


def usage_reflection(
    event_log_path: Optional[str] = None,
    days: int = _DEFAULT_WINDOW_DAYS,
    lang: str = "ja",
    now: Optional[float] = None,
) -> str:
    """集計から促しの一言までを一括で行う便利関数（空なら何も言わない）。"""
    summary = usage_summary(event_log_path=event_log_path, days=days, now=now)
    return usage_nudge(summary, lang=lang)
