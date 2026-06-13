"""
日次アクティビティサマリー生成モジュール。

会話ログ・ムード履歴を集計し、アバターがユーザーへ語りかける
「今日のまとめ」「昨日のまとめ」文字列を生成する。
LLM・外部 API 依存なし。標準ライブラリのみ。

主な公開 API:
  daily_summary(date=None, lang="ja") -> dict
      指定日（デフォルト: 今日）の集計辞書を返す。
  summary_greeting(date=None, lang="ja") -> str
      アバターが読み上げられる1文の挨拶文を返す。
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ユーザー/アバター発話の分類は conversation_log を唯一の真実の源とする
# （dashboard と同じ別名集合を共有し、集計の食い違いを防ぐ）。
try:
    from conversation_log import USER_EVENT_TYPES, AVATAR_EVENT_TYPES
except Exception:  # pragma: no cover - defensive fallback
    USER_EVENT_TYPES = frozenset({"user_comment", "user"})
    AVATAR_EVENT_TYPES = frozenset({"avatar_reply", "avatar"})

# ---------------------------------------------------------------------------
# デフォルトパス（他モジュールと同じ規則）
# ---------------------------------------------------------------------------

_DEFAULT_EVENT_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "avatar_events.jsonl",
)
_DEFAULT_MOOD_HISTORY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "mood_history.jsonl",
)

# ---------------------------------------------------------------------------
# 集計コア
# ---------------------------------------------------------------------------

def _load_jsonl(path: str) -> List[Dict]:
    """JSONL ファイルをロードし、デコード失敗行はスキップする。"""
    entries: List[Dict] = []
    if not os.path.exists(path):
        return entries
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
    return entries


def _date_str(ts: float) -> str:
    """Unix タイムスタンプを "YYYY-MM-DD" 文字列に変換する。"""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def daily_summary(
    target_date: Optional[date] = None,
    lang: str = "ja",
    event_log_path: Optional[str] = None,
    mood_history_path: Optional[str] = None,
) -> Dict:
    """指定日（デフォルト: 今日）のアクティビティ集計辞書を返す。

    Returns:
        {
          "date": "YYYY-MM-DD",
          "user_messages": int,
          "avatar_replies": int,
          "total_interactions": int,
          "peak_hour": int | None,
          "affinity": float | None,
          "affinity_level": str | None,
          "affinity_change": float | None,   # vs previous day's snapshot (None if none)
          "event_counts": {event_type: count, ...},
        }
    """
    if target_date is None:
        target_date = date.today()
    date_key = target_date.strftime("%Y-%m-%d")

    event_log = event_log_path or _DEFAULT_EVENT_LOG
    mood_hist = mood_history_path or _DEFAULT_MOOD_HISTORY

    # ── 会話イベント集計 ──────────────────────────────────────────────────
    events = _load_jsonl(event_log)
    day_events = [
        ev for ev in events
        if _date_str(ev.get("timestamp", 0)) == date_key
    ]

    event_type_counts: Counter = Counter(ev.get("event_type", "") for ev in day_events)
    user_msgs = sum(event_type_counts.get(t, 0) for t in USER_EVENT_TYPES)
    avatar_replies = sum(event_type_counts.get(t, 0) for t in AVATAR_EVENT_TYPES)
    total = user_msgs + avatar_replies

    # ピーク時間帯（ユーザー発話が最も多い時）。
    # 「あなたが一番活発だった時間帯」なので user イベントのみを数える。
    # dashboard の /stats と同じ定義にして両画面の表示が食い違わないようにする。
    hour_counts: defaultdict = defaultdict(int)
    for ev in day_events:
        if ev.get("event_type") not in USER_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if ts:
            try:
                hour_counts[datetime.fromtimestamp(ts).hour] += 1
            except (OSError, OverflowError, ValueError):
                pass
    peak_hour: Optional[int] = None
    if hour_counts:
        peak_hour = max(hour_counts, key=lambda h: hour_counts[h])

    # ── ムード集計 ────────────────────────────────────────────────────────
    mood_entries = _load_jsonl(mood_hist)
    day_moods = [
        e for e in mood_entries
        if e.get("date") == date_key
    ]

    affinity: Optional[float] = None
    affinity_lvl: Optional[str] = None
    affinity_change: Optional[float] = None

    if day_moods:
        last_entry = day_moods[-1]
        affinity = last_entry.get("affinity")
        affinity_lvl = last_entry.get("level")
        # 変化量は「前日（対象日より前の最新スナップショット）」との差で算出する。
        # 履歴は 1 日 1 エントリ（同日は上書き）なので同日内差分は取れず、
        # 旧実装の len(day_moods) >= 2 は決して成立せず affinity_change が常に
        # None になっていた（あいさつの増減メッセージが発火しないバグ）。
        prior_moods = [e for e in mood_entries if e.get("date", "") < date_key]
        if prior_moods and affinity is not None:
            prev_affinity = prior_moods[-1].get("affinity")
            if prev_affinity is not None:
                affinity_change = affinity - prev_affinity

    return {
        "date": date_key,
        "user_messages": user_msgs,
        "avatar_replies": avatar_replies,
        "total_interactions": total,
        "peak_hour": peak_hour,
        "affinity": affinity,
        "affinity_level": affinity_lvl,
        "affinity_change": affinity_change,
        "event_counts": dict(event_type_counts),
    }


# ---------------------------------------------------------------------------
# グリーティング生成
# ---------------------------------------------------------------------------

_GREETINGS: Dict[str, Dict] = {
    "ja": {
        "no_data": "今日はまだ会話がありませんね。気軽に話しかけてください！",
        "few": "{total}回お話ししましたね。",
        "many": "たくさんお話ししました！{total}回も。",
        "affinity_up": "好感度が上がっています（+{delta:.1f}）。嬉しいです！",
        "affinity_down": "好感度が少し下がりました（{delta:.1f}）。どうかしましたか？",
        "peak": "一番活発だった時間帯は{hour}時台でした。",
        "yesterday_prefix": "昨日は",
        "today_prefix": "今日は",
    },
    "en": {
        "no_data": "No conversations yet today. Feel free to say hi!",
        "few": "we chatted {total} time(s).",
        "many": "we chatted a lot — {total} times!",
        "affinity_up": "Our bond is growing (+{delta:.1f})! That makes me happy.",
        "affinity_down": "Our bond dropped a bit ({delta:.1f}). Is everything okay?",
        "peak": "You were most active around {hour}:00.",
        "yesterday_prefix": "Yesterday, ",
        "today_prefix": "Today, ",
    },
}


def summary_greeting(
    target_date: Optional[date] = None,
    lang: str = "ja",
    event_log_path: Optional[str] = None,
    mood_history_path: Optional[str] = None,
) -> str:
    """アバターが読み上げられる1〜2文のサマリー挨拶文を返す。

    データが無い場合はデフォルト文を返す。
    """
    lang_key = lang[:2] if lang[:2] in _GREETINGS else "en"
    msgs = _GREETINGS[lang_key]

    s = daily_summary(
        target_date=target_date,
        lang=lang,
        event_log_path=event_log_path,
        mood_history_path=mood_history_path,
    )

    total = s["total_interactions"]
    is_today = (target_date is None or target_date == date.today())
    prefix = msgs["today_prefix"] if is_today else msgs["yesterday_prefix"]

    parts: List[str] = []

    if total == 0:
        parts.append(msgs["no_data"])
    elif total <= 5:
        parts.append(prefix + msgs["few"].format(total=total))
    else:
        parts.append(prefix + msgs["many"].format(total=total))

    if s["peak_hour"] is not None and total > 0:
        parts.append(msgs["peak"].format(hour=s["peak_hour"]))

    change = s.get("affinity_change")
    if change is not None:
        if change > 0:
            parts.append(msgs["affinity_up"].format(delta=change))
        elif change < 0:
            parts.append(msgs["affinity_down"].format(delta=change))

    # 日本語は句点で区切れるので連結、英語は文間にスペースを入れる
    sep = "" if lang_key == "ja" else " "
    return sep.join(parts)


# ---------------------------------------------------------------------------
# 昨日のサマリー（朝の挨拶でよく使う）
# ---------------------------------------------------------------------------

def yesterday_summary(lang: str = "ja", **kwargs) -> Dict:
    """昨日の集計辞書を返す。"""
    yesterday = date.today() - timedelta(days=1)
    return daily_summary(target_date=yesterday, lang=lang, **kwargs)


def yesterday_greeting(lang: str = "ja", **kwargs) -> str:
    """昨日のサマリー挨拶文を返す（朝の挨拶に利用）。"""
    yesterday = date.today() - timedelta(days=1)
    return summary_greeting(target_date=yesterday, lang=lang, **kwargs)
