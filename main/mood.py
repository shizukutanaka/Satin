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
import threading
import time
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
           "ばか", "馬鹿", "最悪", "だまれ", "黙れ"],
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
    ):
        self.affinity = _clamp(float(affinity))
        self.interactions = int(interactions)
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
        norm = str(text).lower()

        pos_hits = sum(1 for w in self._all_words(self._positive)
                       if w and w.lower() in norm)
        neg_hits = sum(1 for w in self._all_words(self._negative)
                       if w and w.lower() in norm)

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
    def to_dict(self) -> Dict:
        return {
            "affinity": self.affinity,
            "interactions": self.interactions,
            "last_interaction_time": self._last_interaction_time,
            "first_interaction_time": self._first_interaction_time,
            "last_anniversary_days": self._last_anniversary_days,
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
                    lines = [l for l in f.readlines() if l.strip()]

            # 最終行が今日なら上書き、それ以外なら追記
            # レベル変化検出: 同日上書き時は前日以前のエントリと比較して
            # 初回記録時の遷移フラグを失わないようにする
            if lines:
                try:
                    last = json.loads(lines[-1])
                    is_same_day = last.get("date") == today
                    # 比較対象は「今日以前の最後の別日エントリ」
                    if is_same_day:
                        # 同日上書き: 2 行前（前日以前）のエントリとレベルを比較
                        prev_day_entry = json.loads(lines[-2]) if len(lines) >= 2 else None
                    else:
                        prev_day_entry = last
                    if prev_day_entry is not None:
                        prev_level = prev_day_entry.get("level")
                        if prev_level and prev_level != self.level:
                            entry["level_changed"] = True
                            entry["prev_level"] = prev_level
                    new_line = json.dumps(entry, ensure_ascii=False)
                    if is_same_day:
                        lines[-1] = new_line
                    else:
                        lines.append(new_line)
                except (json.JSONDecodeError, IndexError):
                    lines.append(json.dumps(entry, ensure_ascii=False))
            else:
                lines.append(json.dumps(entry, ensure_ascii=False))

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
        return cls(
            affinity=data.get("affinity", AFFINITY_START),
            interactions=data.get("interactions", 0),
            last_interaction_time=data.get("last_interaction_time", 0.0),
            first_interaction_time=data.get("first_interaction_time", 0.0),
            last_anniversary_days=data.get("last_anniversary_days", 0),
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
        except (OSError, OverflowError, ValueError):
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
    key = "level_up" if direction == "up" else "level_down"
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    options = _MILESTONE_MESSAGES[key][lang_key]

    import random
    message = random.choice(options)

    return {
        "direction": direction,
        "from_level": before_level,
        "to_level": after_level,
        "message": message,
    }


# --------------------------------------------------------------------------- #
# 長期不在メッセージ
# --------------------------------------------------------------------------- #

def absence_message(tracker: "MoodTracker", lang: str = "ja") -> str:
    """前回の会話から 24 時間以上経過していた場合に不在への言及メッセージを返す。

    初回・会話回数 0・24 時間未満の場合は空文字。
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
    if str(lang).lower().startswith("en"):
        if elapsed_days == 1:
            return "It's been a day since we last spoke. I missed you!"
        return f"It's been {elapsed_days} days since we last spoke. I really missed you!"
    else:
        if elapsed_days == 1:
            return "昨日ぶりだね。会いたかったよ！"
        return f"{elapsed_days}日ぶりだね。ずっと待ってたよ！"


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
