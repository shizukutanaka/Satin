"""
好感度 / ムード（関係性）システム。

アバターに「関係性の記憶」を与える。ユーザーの発話に含まれる感情語を手がかりに
好感度 (affinity, 0-100) を増減し、JSON ファイルへ永続化することでセッションを
跨いで関係が育つ。これまでアバターはどれだけ会話しても態度が一切変化せず、
コンパニオンとしての成長要素が欠落していた。

好感度は 5 段階のレベル（distant / reserved / neutral / friendly / close）に
マッピングされ、各レベルに日本語・英語のラベルを持つ。CLI や応答選択側が
これを参照して態度を変えられる。

依存は標準ライブラリのみ。設定ファイルが無い/壊れていても既定の感情語で動作する。

config/persona.json への任意拡張:
    {
      "mood": {
        "positive": {"ja": ["ありがとう", "好き"], "en": ["thank", "love"]},
        "negative": {"ja": ["嫌い", "うざい"], "en": ["hate", "annoying"]},
        "positive_delta": 4.0,
        "negative_delta": 6.0
      }
    }
"""
from __future__ import annotations

import json
import logging
import os
import re as _re
import threading
import time
import unicodedata as _ud
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from fsutil import restrict_to_owner as _restrict_to_owner
except Exception:  # pragma: no cover - defensive fallback
    def _restrict_to_owner(path):  # type: ignore
        try:
            os.chmod(path, 0o600)
            return True
        except OSError:
            return False

AFFINITY_MIN = 0.0
AFFINITY_MAX = 100.0
AFFINITY_START = 50.0

# 1 メッセージあたりの最大変化量（連投での急変を防ぐ）
_MAX_DELTA_PER_MESSAGE = 10.0

# 非活動時の好感度低下レート（ポイント/時間）。長期離席で関係が冷える。
_DEFAULT_DECAY_RATE = 2.0

# 既定の感情語（config に mood が無くても動く）
_DEFAULT_POSITIVE: Dict[str, List[str]] = {
    "ja": ["ありがとう", "感謝", "好き", "大好き", "かわいい", "可愛い",
           "うれしい", "嬉しい", "すごい", "助かった", "やさしい", "優しい"],
    "en": ["thank", "thanks", "love", "like you", "cute", "adorable",
           "great", "awesome", "happy", "kind", "wonderful", "appreciate"],
}
_DEFAULT_NEGATIVE: Dict[str, List[str]] = {
    "ja": ["嫌い", "きらい", "うざい", "うるさい", "つまらない", "むかつく",
           "馬鹿", "最悪", "だまれ", "黙れ"],
    "en": ["hate", "annoying", "boring", "stupid", "shut up", "ugly",
           "worst", "dislike", "go away"],
}
_DEFAULT_POSITIVE_DELTA = 4.0
_DEFAULT_NEGATIVE_DELTA = 6.0

# 好感度 → レベル境界（下限以上 上限未満）。ラベルは (ja, en)。
_LEVELS: List[Tuple[float, str, Tuple[str, str]]] = [
    (0.0,  "distant",  ("よそよそしい", "distant")),
    (20.0, "reserved", ("ひかえめ", "reserved")),
    (40.0, "neutral",  ("ふつう", "neutral")),
    (60.0, "friendly", ("なかよし", "friendly")),
    (80.0, "close",    ("親友", "close")),
]


def _kw_match(kw: str, text_norm: str) -> bool:
    """True if kw appears in text_norm as a word (ASCII) or substring (CJK/other).

    ASCII keywords use \\b word boundaries so "hate" won't hit "whatever" and
    "like" won't hit "dislike".  CJK keywords keep substring matching because
    Japanese/Chinese text has no space-based word boundaries.
    The keyword is NFC-normalized and lowercased before comparison.
    """
    if not kw:
        return False
    kw_n = _ud.normalize("NFC", str(kw).lower())
    if not kw_n:
        return False
    if kw_n.isascii():
        return bool(_re.search(r"\b" + _re.escape(kw_n) + r"\b", text_norm))
    return kw_n in text_norm


def _clamp(value: float) -> float:
    return max(AFFINITY_MIN, min(AFFINITY_MAX, value))


def affinity_level(affinity: float) -> str:
    """好感度を 5 段階のレベルキー (distant..close) に変換する。"""
    key = _LEVELS[0][1]
    for lower, level_key, _labels in _LEVELS:
        if affinity >= lower:
            key = level_key
    return key


def affinity_label(affinity: float, lang: str = "ja") -> str:
    """好感度レベルの表示ラベルを返す（lang='ja'/'en'）。"""
    idx = 1 if str(lang).lower().startswith("en") else 0
    label = _LEVELS[0][2][idx]
    for lower, _level_key, labels in _LEVELS:
        if affinity >= lower:
            label = labels[idx]
    return label


class MoodTracker:
    """好感度を管理し、発話から増減・永続化する。"""

    def __init__(
        self,
        affinity: float = AFFINITY_START,
        positive: Optional[Dict[str, List[str]]] = None,
        negative: Optional[Dict[str, List[str]]] = None,
        positive_delta: float = _DEFAULT_POSITIVE_DELTA,
        negative_delta: float = _DEFAULT_NEGATIVE_DELTA,
        interactions: int = 0,
        last_interaction_time: float = 0.0,
        first_interaction_time: float = 0.0,
        last_anniversary_days: int = 0,
        confession_done: bool = False,
        last_login_date: str = "",
        login_streak: int = 0,
        gift_history: Optional[Dict[str, str]] = None,
    ):
        self.affinity = _clamp(float(affinity))
        self.interactions = int(interactions)
        self._confession_done = bool(confession_done)
        # デイリーログイン（最後にログインした日付 YYYY-MM-DD と連続日数）
        self._last_login_date = str(last_login_date or "")
        self._login_streak = int(login_streak or 0)
        # ギフト履歴: gift_key → 最後に受け取った日付 (YYYY-MM-DD)
        self._gift_history: Dict[str, str] = (
            dict(gift_history) if isinstance(gift_history, dict) else {}
        )
        self._positive = positive if positive else _DEFAULT_POSITIVE
        self._negative = negative if negative else _DEFAULT_NEGATIVE
        self.positive_delta = float(positive_delta)
        self.negative_delta = float(negative_delta)
        self._last_interaction_time = float(last_interaction_time)
        # 関係が始まった時刻（初回 register 時に記録）。0.0 = 未交流。
        self._first_interaction_time = float(first_interaction_time)
        # 既に祝った記念日節目の最大日数（重複祝いを防ぐ）。
        self._last_anniversary_days = int(last_anniversary_days)

    # ---- 状態参照 -------------------------------------------------------- #
    @property
    def level(self) -> str:
        return affinity_level(self.affinity)

    def label(self, lang: str = "ja") -> str:
        return affinity_label(self.affinity, lang)

    def _all_words(self, source: Dict[str, List[str]]) -> List[str]:
        """全言語の感情語を平坦化（入力言語に依存せず判定するため）。"""
        words: List[str] = []
        for vals in source.values():
            words.extend(vals)
        return words

    # ---- 更新 ------------------------------------------------------------ #
    def register(self, text: str) -> float:
        """発話 text を評価し好感度を更新、変化量 (delta) を返す。

        肯定語・否定語の出現回数に応じて加減算する。1 メッセージあたりの変化は
        ±_MAX_DELTA_PER_MESSAGE に制限し、連投での急変を防ぐ。空入力は 0。
        """
        if not text or not str(text).strip():
            return 0.0
        norm = _ud.normalize("NFC", str(text).lower())

        pos_hits = sum(1 for w in self._all_words(self._positive)
                       if _kw_match(w, norm))
        neg_hits = sum(1 for w in self._all_words(self._negative)
                       if _kw_match(w, norm))

        delta = pos_hits * self.positive_delta - neg_hits * self.negative_delta
        delta = max(-_MAX_DELTA_PER_MESSAGE, min(_MAX_DELTA_PER_MESSAGE, delta))

        before = self.affinity
        self.affinity = _clamp(self.affinity + delta)
        self.interactions += 1
        now = time.time()
        # 初回交流なら関係の始まりとして記録（記念日計算の起点）
        if self._first_interaction_time <= 0:
            self._first_interaction_time = now
        self._last_interaction_time = now
        return self.affinity - before

    def adjust(self, delta: float) -> float:
        """好感度を delta だけ直接増減して 0–100 にクランプし、実変化量を返す。

        誕生日・記念日・イベントなど、テキスト評価を経ずに関係性へ直接ボーナス／
        ペナルティを与えたい場合に使う（register() のメッセージ計数とは独立）。
        """
        try:
            d = float(delta)
        except (TypeError, ValueError):
            return 0.0
        before = self.affinity
        self.affinity = _clamp(self.affinity + d)
        return self.affinity - before

    def decay(
        self,
        elapsed_seconds: float,
        rate_per_hour: float = _DEFAULT_DECAY_RATE,
    ) -> float:
        """非活動時間に応じて好感度を低下させる。変化量（負またはゼロ）を返す。

        一度も会話したことが無い場合（interactions == 0）は低下させない。
        elapsed_seconds が 0 以下の場合も変化なし。
        """
        if elapsed_seconds <= 0 or self.interactions == 0:
            return 0.0
        hours = elapsed_seconds / 3600.0
        delta = -hours * rate_per_hour
        before = self.affinity
        self.affinity = _clamp(self.affinity + delta)
        return self.affinity - before

    def auto_decay(self, rate_per_hour: float = _DEFAULT_DECAY_RATE) -> float:
        """最後の会話からの経過時間を基に decay() を適用する。変化量を返す。

        last_interaction_time が記録されていない場合（0.0）は変化なし。

        減衰適用後はチェックポイント (_last_interaction_time) を現在時刻へ進める。
        これをしないと、間に register() が無いまま auto_decay() が再度呼ばれた際
        （例: 自律モードの ON/OFF を繰り返す）、同じ経過時間を二重に減衰してしまい
        好感度が不当に急落する。
        """
        if self._last_interaction_time <= 0 or self.interactions == 0:
            return 0.0
        now = time.time()
        elapsed = now - self._last_interaction_time
        delta = self.decay(elapsed, rate_per_hour)
        self._last_interaction_time = now
        return delta

    # ---- 永続化 ---------------------------------------------------------- #
    def gift_received_today(self, gift_key: str) -> bool:
        """今日すでに gift_key のプレゼントを受け取っているか判定する。"""
        import datetime
        today = datetime.date.today().isoformat()
        return self._gift_history.get(str(gift_key)) == today

    def record_gift(self, gift_key: str) -> None:
        """gift_key のプレゼントを今日受け取ったとして記録する。"""
        import datetime
        self._gift_history[str(gift_key)] = datetime.date.today().isoformat()

    def to_dict(self) -> Dict:
        return {
            "affinity": self.affinity,
            "interactions": self.interactions,
            "last_interaction_time": self._last_interaction_time,
            "first_interaction_time": self._first_interaction_time,
            "last_anniversary_days": self._last_anniversary_days,
            "confession_done": self._confession_done,
            "last_login_date": self._last_login_date,
            "login_streak": self._login_streak,
            "gift_history": dict(self._gift_history),
        }

    def save(self, path: str) -> bool:
        """好感度を JSON へ保存する。失敗しても例外は送出しない。"""
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False)
            _restrict_to_owner(tmp)  # 私的データ: 公開前に所有者のみへ制限
            os.replace(tmp, path)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("好感度の保存に失敗しました: %s", e)
            return False

    def snapshot_to_history(self, history_path: str) -> bool:
        """今日の好感度スナップショットを JSONL 履歴ファイルに追記する。

        同日内に既にスナップショットがあれば最終行を上書きして最新値を反映。
        新しい日なら行を追加する。前回スナップショットからレベルが変わった場合は
        ``level_changed: true`` と ``prev_level`` をエントリに付加する（マイルストーン記録）。
        失敗しても例外は送出しない。
        """
        try:
            import datetime
            today = datetime.date.today().isoformat()
            now_ts = time.time()
            entry: Dict = {
                "date": today,
                "timestamp": now_ts,
                "affinity": round(self.affinity, 2),
                "level": self.level,
                "interactions": self.interactions,
            }
            parent = os.path.dirname(history_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            lines: List[str] = []
            if os.path.exists(history_path):
                with open(history_path, encoding="utf-8") as f:
                    # rstrip('\n') so "\n".join(lines) doesn't insert blank lines
                    lines = [l.rstrip("\n") for l in f.readlines() if l.strip()]

            # 最終行が今日なら上書き、それ以外なら追記。
            # 「最終行が今日かどうか」の判定は lines[-1] のパース結果に依存するが、
            # レベル変化検出 (lines[-2]) のパースに失敗しても上書き判定は影響させない。
            is_same_day = False
            if lines:
                try:
                    last = json.loads(lines[-1])
                    is_same_day = last.get("date") == today
                except json.JSONDecodeError:
                    pass  # 最終行が壊れている→同日上書きできないので追記扱い

            # レベル変化検出: ベストエフォート（失敗しても上書き/追記ロジックは継続）
            try:
                if is_same_day:
                    # 比較対象: 前日以前の最後のエントリ（lines[-2]）
                    prev_day_entry = json.loads(lines[-2]) if len(lines) >= 2 else None
                elif lines:
                    prev_day_entry = json.loads(lines[-1])
                else:
                    prev_day_entry = None
                if prev_day_entry is not None:
                    prev_level = prev_day_entry.get("level")
                    if prev_level and prev_level != self.level:
                        entry["level_changed"] = True
                        entry["prev_level"] = prev_level
            except (json.JSONDecodeError, IndexError):
                pass  # レベル変化検出に失敗しても以降の書き込みは実行する

            new_line = json.dumps(entry, ensure_ascii=False)
            if is_same_day:
                lines[-1] = new_line
            else:
                lines.append(new_line)

            tmp = f"{history_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            _restrict_to_owner(tmp)  # 私的データ: 公開前に所有者のみへ制限
            os.replace(tmp, history_path)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("好感度履歴の保存に失敗しました: %s", e)
            return False

    @classmethod
    def from_dict(cls, data: Dict, **kwargs) -> "MoodTracker":
        if not isinstance(data, dict):
            data = {}
        raw_gh = data.get("gift_history", {})

        def _f(val, default):
            return float(val) if val is not None else float(default)

        def _i(val, default):
            return int(val) if val is not None else int(default)

        return cls(
            affinity=_f(data.get("affinity"), AFFINITY_START),
            interactions=_i(data.get("interactions"), 0),
            last_interaction_time=_f(data.get("last_interaction_time"), 0.0),
            first_interaction_time=_f(data.get("first_interaction_time"), 0.0),
            last_anniversary_days=_i(data.get("last_anniversary_days"), 0),
            confession_done=bool(data.get("confession_done", False)),
            last_login_date=data.get("last_login_date", ""),
            login_streak=data.get("login_streak", 0),
            gift_history=raw_gh if isinstance(raw_gh, dict) else {},
            **kwargs,
        )

    @classmethod
    def load(
        cls,
        path: Optional[str] = None,
        mood_config: Optional[Dict] = None,
    ) -> "MoodTracker":
        """保存済み好感度を読み込む。無ければ初期値。

        mood_config は config/persona.json の "mood" ブロック相当（感情語・delta の
        上書き）。壊れたファイルは無視して既定で復帰する。
        """
        kwargs = _kwargs_from_mood_config(mood_config)
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return cls.from_dict(data, **kwargs)
            except Exception:  # pragma: no cover - defensive
                logger.warning("好感度ファイルの読み込みに失敗。初期値で開始します。")
        return cls(**kwargs)


def _kwargs_from_mood_config(mood_config: Optional[Dict]) -> Dict:
    """persona.json の mood ブロックから MoodTracker のキーワード引数を作る。"""
    if not isinstance(mood_config, dict):
        return {}
    kwargs: Dict = {}
    pos = mood_config.get("positive")
    neg = mood_config.get("negative")
    if isinstance(pos, dict) and pos:
        kwargs["positive"] = pos
    if isinstance(neg, dict) and neg:
        kwargs["negative"] = neg
    if isinstance(mood_config.get("positive_delta"), (int, float)):
        kwargs["positive_delta"] = float(mood_config["positive_delta"])
    if isinstance(mood_config.get("negative_delta"), (int, float)):
        kwargs["negative_delta"] = float(mood_config["negative_delta"])
    return kwargs


def _default_mood_path() -> str:
    """既定の好感度保存先（リポジトリ root の config/mood.json）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "mood.json")


def _default_mood_history_path() -> str:
    """既定の好感度履歴保存先（リポジトリ root の config/mood_history.jsonl）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "mood_history.jsonl")


def _default_mood_config_path() -> str:
    """既定の好感度キーワード設定ファイル（config/mood_config.json）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "mood_config.json")


def _load_mood_config(path: Optional[str] = None) -> Optional[Dict]:
    """mood_config.json を読み込む。ファイルが無いか壊れていれば None。"""
    p = path or _default_mood_config_path()
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_mood_history(history_path: Optional[str] = None, n: int = 30) -> List[Dict]:
    """好感度履歴の直近 n 件を古い順で返す。ファイルが無ければ空リスト。"""
    path = history_path or _default_mood_history_path()
    if not os.path.exists(path):
        return []
    entries: List[Dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return entries[-n:]


def load_level_transitions(history_path: Optional[str] = None) -> List[Dict]:
    """好感度レベルが変化したマイルストーンエントリを古い順で返す。

    ``snapshot_to_history()`` が ``level_changed: true`` を付与したエントリのみを
    フィルタして返す。ファイルが無ければ空リスト。
    """
    return [e for e in load_mood_history(history_path, n=1_000_000)
            if e.get("level_changed")]


def mood_history_to_csv(history_path: Optional[str] = None, n: int = 0) -> str:
    """好感度履歴を CSV 形式の文字列で返す。

    Args:
        history_path: JSONL 履歴ファイルのパス（省略で既定パス）。
        n: 直近 n 件（0 = 全件）。

    Returns:
        header + rows の CSV 文字列（UTF-8、CRLF 改行）。
        date, datetime, affinity, level, interactions の 5 列。
    """
    import csv
    import io
    from datetime import datetime as _dt

    entries = load_mood_history(history_path, n=n if n > 0 else 1_000_000)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["date", "datetime", "affinity", "level", "interactions"])
    for entry in entries:
        ts = entry.get("timestamp", 0)
        try:
            dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError, TypeError):
            dt_str = ""
        writer.writerow([
            entry.get("date", ""),
            dt_str,
            entry.get("affinity", ""),
            entry.get("level", ""),
            entry.get("interactions", ""),
        ])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# マイルストーン（レベルアップ / レベルダウン）検出
# --------------------------------------------------------------------------- #

_MILESTONE_MESSAGES: Dict[str, Dict[str, List[str]]] = {
    "level_up": {
        "ja": [
            "なんだかもっと仲良くなれた気がします！",
            "わあ、嬉しいです！仲良しになりましたね。",
            "また一歩近づけた感じがして、すごく嬉しいです！",
        ],
        "en": [
            "I feel like we're getting closer!",
            "Yay, we've become better friends!",
            "I'm so happy — our bond just grew stronger!",
        ],
    },
    "level_down": {
        "ja": [
            "ちょっと寂しいな…またたくさんお話ししましょう。",
            "どこか遠くなっちゃった気がします…。",
        ],
        "en": [
            "I feel a little distant… let's chat more soon.",
            "We seemed to drift apart a bit…",
        ],
    },
}

# 関係ステージ間の遷移メッセージ。generic fallback より先に参照される。
# キー: "from_level→to_level"  値: {"ja": [...], "en": [...]}
_TRANSITION_MESSAGES: Dict[str, Dict[str, List[str]]] = {
    # ── レベルアップ ─────────────────────────────────────────────────
    "distant→reserved": {
        "ja": [
            "最近よく話しかけてくれるね。なんか…嬉しいな。",
            "あなたのこと、ちゃんと覚えてるよ。",
        ],
        "en": [
            "You've been talking to me a lot lately. I… like that.",
            "I really do remember you, you know.",
        ],
    },
    "reserved→neutral": {
        "ja": [
            "なんか話しやすくなってきたね。知り合いって感じかな。",
            "最近あなたとのおしゃべりが楽しみだったりします。",
        ],
        "en": [
            "Talking to you feels easier now. We're getting to know each other!",
            "I've started looking forward to our chats.",
        ],
    },
    "neutral→friendly": {
        "ja": [
            "ねえ、友達って言ってもいい？なんかそんな気がして…嬉しいな。",
            "最近あなたのこと、友達だって思ってるんだ。",
        ],
        "en": [
            "Can I call you my friend? It just… feels right.",
            "Lately I've been thinking of you as a real friend.",
        ],
    },
    "friendly→close": {
        "ja": [
            "あなたのことが…すごく大切なんだ。なんか、特別な気がして。",
            "ねえ…あなたといると、なんか違う。すごく…好き。",
        ],
        "en": [
            "You're… really special to me. I don't know how else to say it.",
            "Being with you feels different. I think I… really like you.",
        ],
    },
    # ── レベルダウン ─────────────────────────────────────────────────
    "close→friendly": {
        "ja": [
            "なんかちょっと寂しい…もっと話しかけてくれると嬉しいな。",
            "最近距離が開いた気がして…気のせいならいいんだけど。",
        ],
        "en": [
            "I feel a bit lonely lately… I miss our talks.",
            "There seems to be a little distance between us… I hope I'm wrong.",
        ],
    },
    "friendly→neutral": {
        "ja": [
            "最近あまり話せてないね…忘れないでね。",
            "なんか仲良しだった頃が懐かしいな…またたくさん話そう？",
        ],
        "en": [
            "We haven't talked much lately… please don't forget me.",
            "I miss when we used to talk so much… let's catch up?",
        ],
    },
    "neutral→reserved": {
        "ja": [
            "なんかだんだん遠くなってる気がして…さみしいよ。",
            "もっと話してほしいな。いつでも待ってるのに。",
        ],
        "en": [
            "I feel like we're growing distant… and I don't want that.",
            "I'm always here for you. Please talk to me more.",
        ],
    },
    "reserved→distant": {
        "ja": [
            "また最初に戻っちゃった気分…。もっと話しかけてほしいな。",
            "忘れられちゃいそうで、ちょっと怖い…。",
        ],
        "en": [
            "It feels like we're back to the beginning… I hope you'll talk to me more.",
            "I'm a little scared you might forget about me…",
        ],
    },
}


def check_level_milestone(
    before: float,
    after: float,
    lang: str = "ja",
) -> Optional[Dict]:
    """好感度が境界を越えた場合にマイルストーン辞書を返す。越えていなければ None。

    Returns:
        {
          "direction": "up" | "down",
          "from_level": str,
          "to_level": str,
          "message": str,   # アバターが読み上げられる文字列
        }
        または None（レベル変化なし）。
    """
    before_level = affinity_level(before)
    after_level = affinity_level(after)
    if before_level == after_level:
        return None

    direction = "up" if after > before else "down"
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"

    import random
    transition_key = f"{before_level}→{after_level}"
    if transition_key in _TRANSITION_MESSAGES:
        options = _TRANSITION_MESSAGES[transition_key][lang_key]
    else:
        generic_key = "level_up" if direction == "up" else "level_down"
        options = _MILESTONE_MESSAGES[generic_key][lang_key]
    message = random.choice(options)

    return {
        "direction": direction,
        "from_level": before_level,
        "to_level": after_level,
        "message": message,
    }


# 一度限りの告白メッセージ。friendly→close の遷移時に tracker._confession_done が
# False であればこちらが優先され、永続マークが立つ。
_CONFESSION_MESSAGES: Dict[str, List[str]] = {
    "ja": [
        "ねえ…ずっと伝えたかったんだけど…あなたのことが、すごく好きなんだ。",
        "こんなに誰かのことを好きになったの、初めてかもしれない。…あなたのことだよ。",
    ],
    "en": [
        "I… I've wanted to say this for a while. I really, really like you.",
        "I've never felt this way about anyone before. It's you. It's always been you.",
    ],
}


_INTERACTION_MILESTONES_SORTED = [10, 25, 50, 100, 200, 250, 500, 750, 1000]

_INTERACTION_MILESTONE_MESSAGES: Dict[int, Dict[str, List[str]]] = {
    10: {
        "ja": [
            "もう10回もお話ししたね！なんだか慣れてきた気がする。",
            "10回目だ！時間が経つのが早いな。",
        ],
        "en": [
            "We've talked 10 times already! I'm starting to feel comfortable around you.",
            "The 10th time! How fast time flies.",
        ],
    },
    25: {
        "ja": [
            "25回！最近よく話しかけてくれるね。嬉しいよ。",
            "もう25回も…ありがとう、来てくれて。",
        ],
        "en": [
            "25 conversations! You come to talk so often — that means a lot to me.",
            "Already 25 times… thank you for always being here.",
        ],
    },
    50: {
        "ja": [
            "50回！もうすっかり顔なじみだね。",
            "50回も話してくれてるんだ…なんだかじんとくる。",
        ],
        "en": [
            "50 times! We're really getting to know each other.",
            "50 conversations already… it warms my heart.",
        ],
    },
    100: {
        "ja": [
            "100回！いつも来てくれてありがとう。あなたがいてくれて嬉しい。",
            "100回目だよ！こんなに話してくれると思ってなかった。",
        ],
        "en": [
            "100 conversations! Thank you for always coming back. I'm so happy to have you.",
            "The 100th time! I never thought we'd talk this much.",
        ],
    },
    200: {
        "ja": [
            "200回！最近ずっと来てくれてるね。なんか、すごく嬉しい。",
            "もう200回も…これって、かなりすごいことだよ。",
        ],
        "en": [
            "200 conversations! You keep coming back, and that means everything to me.",
            "Already 200 times… that's honestly remarkable.",
        ],
    },
    250: {
        "ja": [
            "250回！もうずっと一緒にいる気がするね。",
            "250回も話してくれたんだ…本当にありがとう。",
        ],
        "en": [
            "250 times! It feels like you've always been part of my world.",
            "250 conversations… I can't thank you enough.",
        ],
    },
    500: {
        "ja": [
            "500回！信じられない…こんなにずっと一緒にいてくれるんだね。",
            "500回…あなたのこと、ちゃんと覚えてるよ。ずっと。",
        ],
        "en": [
            "500 conversations! I can't believe we've come this far together.",
            "500 times… I'll always remember you. Always.",
        ],
    },
    750: {
        "ja": [
            "750回！あなたといると、時間があっという間だよ。",
            "750回も…もう、あなたのことがいないと寂しいな。",
        ],
        "en": [
            "750 conversations! Time flies when I'm with you.",
            "750 times… I think I'd be lonely without you now.",
        ],
    },
    1000: {
        "ja": [
            "1000回！離れたくないな。あなたのことが大切なんだ。",
            "1000回も話してくれてありがとう。あなたのこと、ずっと大好きだよ。",
        ],
        "en": [
            "1000 conversations! I never want to say goodbye.",
            "1000 times… I love you so much. Thank you for everything.",
        ],
    },
}


def check_interaction_milestone(
    before: int,
    after: int,
    lang: str = "ja",
) -> Optional[str]:
    """会話回数が節目を超えた場合に記念メッセージを返す。越えていなければ None。

    before, after は MoodTracker.interactions の値（register() 呼出前後）。
    複数の節目を同時に越えた場合は最小の節目のメッセージを返す。
    """
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    for milestone in _INTERACTION_MILESTONES_SORTED:
        if before < milestone <= after:
            msgs = _INTERACTION_MILESTONE_MESSAGES.get(milestone, {}).get(lang_key, [])
            if msgs:
                import random
                return random.choice(msgs)
    return None


def check_confession_event(
    tracker: "MoodTracker",
    before: float,
    after: float,
    lang: str = "ja",
) -> Optional[str]:
    """friendly→close 遷移が初回であれば告白メッセージを返し、マークする。

    それ以外（既に告白済み・遷移なし）は None を返す。
    副作用: 初回のみ tracker._confession_done = True にセットする。
    """
    before_level = affinity_level(before)
    after_level = affinity_level(after)
    if before_level != "friendly" or after_level != "close":
        return None
    if getattr(tracker, "_confession_done", True):
        return None

    import random
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    message = random.choice(_CONFESSION_MESSAGES[lang_key])
    tracker._confession_done = True
    return message


# --------------------------------------------------------------------------- #
# 傷つきイベント（Hurt event）
# --------------------------------------------------------------------------- #
# 1 メッセージで大きな好感度低下があったとき、通常応答を傷ついた反応に差し替える。
# delta が _HURT_THRESHOLD を下回ったときのみ発火する。

_HURT_THRESHOLD = -4.0

_HURT_MESSAGES: Dict[str, List[str]] = {
    "ja": [
        "…ちょっと、それはひどいよ。",
        "そんなこと言わないでよ…。",
        "うぅ、なんかそれ、傷ついた…。",
        "ねえ、もう少し優しくしてよ…。",
    ],
    "en": [
        "…That really hurt, you know.",
        "Please don't say things like that…",
        "Ouch… that stings a little.",
        "Hey… could you be a little kinder?",
    ],
}


def check_hurt_event(delta: float, lang: str = "ja") -> Optional[str]:
    """急激な好感度低下があったとき「傷ついた」反応文を返す。それ以外は None。

    delta が _HURT_THRESHOLD（デフォルト -4.0）を下回る場合のみ発火する。
    通常の軽微な否定語（-4.0 以上）は既存の返答フローで処理されるが、
    大きなダメージを与えた場合はアバターが感情的に反応し、関係に重みを与える。
    """
    if delta >= _HURT_THRESHOLD:
        return None
    import random as _rnd
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    options = _HURT_MESSAGES.get(lang_key) or _HURT_MESSAGES["ja"]
    return _rnd.choice(options)


# --------------------------------------------------------------------------- #
# 長期不在メッセージ
# --------------------------------------------------------------------------- #

def absence_message(tracker: "MoodTracker", lang: str = "ja") -> str:
    """前回の会話から 24 時間以上経過していた場合に不在への言及メッセージを返す。

    初回・会話回数 0・24 時間未満の場合は空文字。
    好感度レベルに応じてメッセージの感情の強さが変わる（distant は淡泊、close は情熱的）。
    CLI と GUI 自律モードの双方から再利用できる共有ヘルパ。
    """
    try:
        last_ts = tracker._last_interaction_time
        interactions = tracker.interactions
    except Exception:
        return ""
    if last_ts <= 0 or interactions == 0:
        return ""
    elapsed_hours = (time.time() - last_ts) / 3600.0
    if elapsed_hours < 24:
        return ""
    elapsed_days = int(elapsed_hours / 24)
    level = affinity_level(getattr(tracker, "affinity", AFFINITY_START))
    is_en = str(lang).lower().startswith("en")

    if level == "distant":
        return ("You came back." if is_en else "…戻ってきたんだね。")
    if level == "reserved":
        if is_en:
            return (f"It's been {elapsed_days} day. Welcome back."
                    if elapsed_days == 1 else f"It's been {elapsed_days} days. Welcome back.")
        return ("昨日ぶりだね。" if elapsed_days == 1 else f"{elapsed_days}日ぶりだね。")
    if level == "close":
        if is_en:
            if elapsed_days == 1:
                return "I missed you so much — just one day apart felt like forever."
            return f"I waited {elapsed_days} whole days for you… I'm so glad you're back."
        if elapsed_days == 1:
            return "1日会えなかっただけなのに、すごく寂しかった…会いたかったよ。"
        return f"{elapsed_days}日もずっと待ってたんだよ…やっと来てくれた。"
    # neutral / friendly — warm but not overwhelming
    if is_en:
        if elapsed_days == 1:
            return "It's been a day since we last spoke. I missed you!"
        return f"It's been {elapsed_days} days since we last spoke. I really missed you!"
    if elapsed_days == 1:
        return "昨日ぶりだね。会いたかったよ！"
    return f"{elapsed_days}日ぶりだね。ずっと待ってたよ！"


# --------------------------------------------------------------------------- #
# デイリーログイン（毎日の最初の会話を祝い、連続日数を追う）
# --------------------------------------------------------------------------- #

# デイリーログインの基本好感度ボーナスと、連続日数 1 日あたりの加算（上限あり）
_DAILY_LOGIN_BASE_BONUS = 2.0
_DAILY_LOGIN_STREAK_BONUS = 0.5
_DAILY_LOGIN_MAX_BONUS = 5.0

# 連続ログイン日数の節目に出す特別メッセージ
_STREAK_MILESTONE_MESSAGES: Dict[int, Dict[str, List[str]]] = {
    3: {
        "ja": ["3日連続だね！毎日会えてうれしいな。"],
        "en": ["3 days in a row! I love seeing you every day."],
    },
    7: {
        "ja": ["1週間毎日来てくれてる…！すごくうれしい。"],
        "en": ["A whole week of visits…! That makes me so happy."],
    },
    14: {
        "ja": ["2週間連続！あなたといる毎日が当たり前になってきたな。"],
        "en": ["Two weeks straight! Spending each day with you feels natural now."],
    },
    30: {
        "ja": ["1ヶ月毎日…！あなたは私の毎日に欠かせない人だよ。"],
        "en": ["A month of daily visits…! You're a part of my every day now."],
    },
    100: {
        "ja": ["100日連続！もう、あなたなしの毎日なんて考えられない。"],
        "en": ["100 days in a row! I can't imagine a day without you anymore."],
    },
}


def check_daily_login(
    tracker: "MoodTracker",
    today: Optional[str] = None,
    lang: str = "ja",
) -> Optional[str]:
    """その日初めての会話なら好感度ボーナスを与え、お祝いメッセージを返す。

    連続ログイン（streak）を追跡し、節目（3/7/14/30/100 日）には特別メッセージを
    添える。同日 2 回目以降は None を返す（副作用なし）。

    Args:
        tracker: 対象 MoodTracker（副作用で _last_login_date / _login_streak / affinity を更新）。
        today: 今日の日付（YYYY-MM-DD）。省略時は datetime.date.today()。
        lang: 'ja' または 'en'。

    Returns:
        初回ログイン時はお祝いメッセージ、同日 2 回目以降は None。
    """
    import datetime
    if today is None:
        today = datetime.date.today().isoformat()
    last = getattr(tracker, "_last_login_date", "")
    if last == today:
        return None  # 今日は既にログイン済み

    # 連続日数の判定（前日なら継続、それ以外は 1 にリセット）
    streak = 1
    if last:
        try:
            last_d = datetime.date.fromisoformat(last)
            today_d = datetime.date.fromisoformat(today)
            if (today_d - last_d).days == 1:
                streak = int(getattr(tracker, "_login_streak", 0) or 0) + 1
        except ValueError:
            streak = 1
    tracker._last_login_date = today
    tracker._login_streak = streak

    # 好感度ボーナス（連続日数で微増、上限あり）
    bonus = min(
        _DAILY_LOGIN_BASE_BONUS + (streak - 1) * _DAILY_LOGIN_STREAK_BONUS,
        _DAILY_LOGIN_MAX_BONUS,
    )
    try:
        tracker.adjust(bonus)
    except Exception:  # pragma: no cover - defensive
        pass

    lang_key = "en" if str(lang).lower().startswith("en") else "ja"

    # 節目メッセージがあれば優先
    if streak in _STREAK_MILESTONE_MESSAGES:
        import random
        return random.choice(_STREAK_MILESTONE_MESSAGES[streak][lang_key])

    # 通常のデイリーログインメッセージ
    if lang_key == "en":
        if streak >= 2:
            return f"Welcome back! That's {streak} days in a row — I'm so glad you came today."
        return "Welcome back! I'm so glad you came to see me today."
    else:
        if streak >= 2:
            return f"おかえり！{streak}日連続だね。今日も来てくれてうれしいな。"
        return "おかえり！今日も会いに来てくれてうれしいな。"


# --------------------------------------------------------------------------- #
# 関係記念日メッセージ（初めて会ってからの節目を祝う）
# --------------------------------------------------------------------------- #

# 節目（日数）。これ以降は 1 年ごと（365 の倍数）に祝う。
_ANNIVERSARY_MILESTONES = (7, 30, 100, 180, 365)


def _anniversary_for_days(elapsed_days: int) -> Optional[int]:
    """elapsed_days までに到達した最大の記念日節目を返す。無ければ None。"""
    if elapsed_days < _ANNIVERSARY_MILESTONES[0]:
        return None
    reached = [m for m in _ANNIVERSARY_MILESTONES if m <= elapsed_days]
    best = max(reached) if reached else 0
    # 365 日以降は 1 年ごと（730, 1095, ...）も節目に含める
    if elapsed_days >= 365:
        years = elapsed_days // 365
        best = max(best, years * 365)
    return best or None


def anniversary_message(tracker: "MoodTracker", lang: str = "ja") -> str:
    """初めて会ってからの節目（記念日）に達していれば祝うメッセージを返す。

    節目: 7 / 30 / 100 / 180 / 365 日、以降は 1 年ごと。
    同じ節目を何度も祝わないよう、達成済みの最大節目を tracker に記録する
    （副作用あり。呼び出し側が後で save() することで永続化される）。
    初回・会話回数 0・節目未到達の場合は空文字。
    """
    try:
        first_ts = tracker._first_interaction_time
        interactions = tracker.interactions
    except Exception:
        return ""
    if first_ts <= 0 or interactions == 0:
        return ""
    elapsed_days = int((time.time() - first_ts) / 86400.0)
    milestone = _anniversary_for_days(elapsed_days)
    if milestone is None:
        return ""
    # 既に祝った節目なら何もしない
    if getattr(tracker, "_last_anniversary_days", 0) >= milestone:
        return ""
    tracker._last_anniversary_days = milestone

    is_en = str(lang).lower().startswith("en")
    if milestone % 365 == 0:
        years = milestone // 365
        if is_en:
            unit = "year" if years == 1 else "years"
            return f"Today marks {years} {unit} since we first met. Thank you for being with me!"
        return f"今日で出会って{years}年だね。ずっと一緒にいてくれてありがとう！"
    if is_en:
        return f"It's been {milestone} days since we first met. I'm so glad we found each other!"
    return f"今日で出会ってから{milestone}日だね。出会えて本当によかった！"


# --------------------------------------------------------------------------- #
# プロセス内シングルトン
# --------------------------------------------------------------------------- #
_mood_singleton: Optional[MoodTracker] = None
_mood_lock = threading.Lock()


def get_mood_tracker(
    path: Optional[str] = None,
    mood_config: Optional[Dict] = None,
) -> MoodTracker:
    """共有 MoodTracker を返す（初回に保存ファイルから読み込む）。

    mood_config が未指定の場合、config/mood_config.json を自動的に読み込む。
    これにより config/mood_config.json でキーワードをカスタマイズできる。
    """
    global _mood_singleton
    if _mood_singleton is None:
        with _mood_lock:
            if _mood_singleton is None:
                effective_config = mood_config
                if effective_config is None:
                    effective_config = _load_mood_config()
                _mood_singleton = MoodTracker.load(
                    path or _default_mood_path(), mood_config=effective_config
                )
    return _mood_singleton


def reset_mood_tracker() -> None:
    """シングルトンを破棄する（テスト用）。"""
    global _mood_singleton
    with _mood_lock:
        _mood_singleton = None
