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
    # 感情の向き先判定（無くても従来どおり動く optional 依存）
    from sentiment_target import (
        suppresses_affinity_penalty as _suppresses_affinity_penalty,
    )
except Exception:  # pragma: no cover - defensive fallback
    _suppresses_affinity_penalty = None  # type: ignore[assignment]

try:
    from fsutil import restrict_to_owner as _restrict_to_owner
    from fsutil import load_jsonl_dicts
    from fsutil import atomic_write_text as _atomic_write_text
except Exception:  # pragma: no cover - defensive fallback
    def _restrict_to_owner(path):  # type: ignore
        try:
            os.chmod(path, 0o600)
            return True
        except OSError:
            return False

    def _atomic_write_text(path, content, *, encoding="utf-8", fsync=True, restrict=False):  # type: ignore
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
                f.flush()
                if fsync:
                    os.fsync(f.fileno())
            if restrict:
                _restrict_to_owner(tmp)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load_jsonl_dicts(path, *, encoding="utf-8"):  # type: ignore
        if not os.path.exists(path):
            return []
        out = []
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

AFFINITY_MIN = 0.0
AFFINITY_MAX = 100.0
AFFINITY_START = 50.0

# 1 メッセージあたりの最大変化量（連投での急変を防ぐ）
_MAX_DELTA_PER_MESSAGE = 10.0

# 告白イベントの最低条件。close に達しただけでは足りず、実際に関係が続いて
# いることを要求する（詳細は check_confession_event の docstring）。
# 日数は記念日の最初の節目（7 日）に合わせてある。0 にすると従来どおり即座。
_CONFESSION_MIN_DAYS = 7.0
_CONFESSION_MIN_INTERACTIONS = 20

# 1 日あたりの会話由来の好感度「上昇」上限（同一の肯定語を連投して短時間で
# 関係を最大化する行為を防ぐ）。ギフトの日次クールダウン（全種類を1回ずつ
# 贈った場合の合計 ≈30.5）と同程度の水準に設定。減少（ネガティブな発言への
# ペナルティ）はこの上限の対象外 — 上限は「稼ぎすぎ」だけを防ぎ、正当な
# マイナス影響は薄めない。
#
# **この値が関係の成長弧の長さを決める。** 算術を明示しておく:
#   開始 50.0（neutral）→ close（最高レベル）の閾値 80.0 = 差 30.0
#   → 5.0/日なら最高レベルまで最短 6 日、つまり「セッションを跨いで育つ関係」
#     という製品の謳い文句どおりの弧になる。
# かつての既定は 30.0 で、**初日の 8 メッセージほどで最高レベルに到達**し、
# 成長は 1 セッションで終わっていた。製品オーナーの判断で 5.0 へ変更した
# （告白の下限が「出会いから 7 日」であることとも整合する）。
# 速い弧が欲しい場合は config/mood_config.json の `max_daily_gain` を
# 上げること（コード編集は不要）。
_MAX_DAILY_CONVERSATION_GAIN = 5.0

# 非活動時の好感度低下レート（ポイント/時間）と、低下が始まるまでの猶予（時間）。
#
# **成長と対称にしてある。** 上昇は日次 5.0 が上限（_MAX_DAILY_CONVERSATION_GAIN）
# なので、低下も 0.2/時間 ≒ 4.8/日 とし、離れた日数ぶんだけ戻る形にした。
# かつては 2.0/時間・猶予なしで、実測すると **24 時間で -48（close から
# reserved へ）、40 時間で 0（最低レベル）**。育つのに最短 6 日かかるのに 2 日で
# ゼロになる非対称があり、しかも usage_guardrails は「休んでいいよ」と休息を
# 促すので、製品が休息を勧めておいて休んだ人を罰していた。
#
# 猶予 48 時間は「週末そのぶん離れても関係は冷えない」ための下駄。これを超えた
# ぶんだけが低下の対象になる（1 週間の不在で約 -25）。
_DEFAULT_DECAY_RATE = 0.2
_DECAY_GRACE_HOURS = 48.0

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

# 感情強度連動の重み（研究 A3）。従来は全ての感情語が一律 ±1 カウントだったが、
# 「大好き」は「好き」より強く、「最悪」は「つまらない」より強い。語ごとに弱/中/強の
# 強度重みを与え、好感度の増減幅（register）を強度加重にする。辞書は静的データで
# 推論不要・決定論的。強度指定の無い語（config のカスタム語を含む）は 1.0 のまま
# で、既存の「1 語 = 係数 delta」挙動を保つ。極性の判定（classify_sentiment）は
# 従来どおり整数カウントで行い、強度は「どれだけ動くか」だけに影響する。
# WRIME Ver.2（感情強度＋極性）の知見を軽量に反映（[HF wrime]）。
_DEFAULT_INTENSITY = 1.0
_INTENSITY: Dict[str, float] = {
    # --- 強い肯定 ---
    "大好き": 1.6, "love": 1.5, "adorable": 1.3, "wonderful": 1.3,
    "感謝": 1.2, "嬉しい": 1.1, "うれしい": 1.1,
    # --- やや控えめな肯定 ---
    "like you": 0.8, "すごい": 0.8, "great": 0.9, "awesome": 0.9,
    "kind": 0.9, "やさしい": 0.9, "優しい": 0.9,
    # --- 強い否定 ---
    "最悪": 1.6, "worst": 1.6, "hate": 1.5, "むかつく": 1.4,
    "だまれ": 1.4, "黙れ": 1.4, "馬鹿": 1.3, "stupid": 1.3,
    # --- やや弱い否定 ---
    "つまらない": 0.7, "boring": 0.7, "うるさい": 0.8, "annoying": 0.8,
    "dislike": 0.8, "go away": 0.9,
}
# NFC 小文字化した検索キーで引けるよう正規化した参照表。
_INTENSITY_NORM: Dict[str, float] = {
    _ud.normalize("NFC", str(k).lower()): float(v) for k, v in _INTENSITY.items()
}

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


# ------------------------------------------------------------------
# 否定・強調・絵文字を考慮したハイブリッド感情判定（研究 A2）。
# 従来は肯定/否定語の単純一致で、「好きじゃない」「I don't like you」を肯定と
# 誤判定していた。語の出現位置を見て否定スコープに入っていれば極性を反転
# （否定された肯定=否定）または打ち消し（否定された否定=中立）する。
# LLM 非依存・辞書/ルールのみ・決定論的で、既存の「1 語につき最大 1 カウント」
# のセマンティクスは保つ（否定時のみ極性が変わる）。
# ------------------------------------------------------------------
# 日本語の否定接尾（キーワード直後の窓を前方一致で判定）。な形容詞/名詞的な
# 肯定語（好き・大好き 等）に付く「〜じゃない / 〜ではない」系に限定して
# 誤検出を抑える。
_NEG_SUFFIX_JA = (
    "じゃない", "ではない", "じゃなかった", "ではなかった",
    "じゃありません", "ではありません", "じゃ無い", "では無い",
)
_NEG_WINDOW_JA = 8  # キーワード末尾から何文字先までを否定判定の窓とするか
# 英語の否定語（キーワードの直前の窓に現れるか）。
_NEG_RE_EN = _re.compile(
    r"\b(?:not|never|no|without|hardly|cannot|can't|don't|doesn't|didn't|"
    r"isn't|aren't|wasn't|weren't|won't|couldn't|wouldn't|shouldn't)\b"
)
_NEG_WINDOW_EN = 30  # キーワード開始位置から何文字手前までを否定判定の窓とするか

# 絵文字・顔文字の感情（NFC 正規化・小文字化後のテキストに対して部分一致）。
_EMOJI_POSITIVE = (
    "😊", "😄", "😃", "😍", "🥰", "❤", "♥", "💕", "💖", "👍", "🙂", "😆",
    "✨", "🎉", "☺", "(^^)", "(^_^)", "^_^", "(*^^*)", "(^o^)", "(^▽^)",
)
_EMOJI_NEGATIVE = (
    "😠", "😡", "😢", "😭", "😞", "💢", "👎", "😔", "😩", "😖", "😣",
    "(´；ω；｀)", "(;_;)", "(；＿；)", "orz", "(・_・)", "(´・ω・｀)",
)


def _iter_occurrences(kw_n: str, text_norm: str):
    """kw_n（NFC 小文字化済み）の text_norm 内の出現を (start, end, is_ascii) で列挙。

    ASCII は語境界一致、CJK/その他は部分一致（_kw_match と同じ規則）。
    """
    if not kw_n:
        return
    if kw_n.isascii():
        for m in _re.finditer(r"\b" + _re.escape(kw_n) + r"\b", text_norm):
            yield m.start(), m.end(), True
    else:
        i = text_norm.find(kw_n)
        while i != -1:
            yield i, i + len(kw_n), False
            i = text_norm.find(kw_n, i + 1)


def _is_negated(text_norm: str, start: int, end: int, is_ascii: bool) -> bool:
    """位置 [start, end) のキーワード出現が否定スコープ内かを判定する。"""
    if is_ascii:
        window = text_norm[max(0, start - _NEG_WINDOW_EN):start]
        return bool(_NEG_RE_EN.search(window)) or "n't" in window
    window = text_norm[end:end + _NEG_WINDOW_JA]
    return any(window.startswith(suf) for suf in _NEG_SUFFIX_JA)


def _keyword_contribution(kw: str, text_norm: str, base_positive: bool):
    """キーワード kw の text_norm への感情寄与を 'pos' / 'neg' / None で返す。

    出現が無ければ None。否定されていない出現が 1 つでもあれば本来の極性。
    肯定語が「否定のみ」で現れれば 'neg'（好きじゃない=否定）に反転。
    否定語が「否定のみ」で現れれば None（嫌いじゃない=打ち消し・中立）。
    """
    kw_n = _ud.normalize("NFC", str(kw).lower())
    occ = list(_iter_occurrences(kw_n, text_norm))
    if not occ:
        return None
    any_unnegated = any(not _is_negated(text_norm, s, e, a) for s, e, a in occ)
    if base_positive:
        return "pos" if any_unnegated else "neg"
    return "neg" if any_unnegated else None


def _emoji_counts(text_norm: str) -> Tuple[int, int]:
    """text_norm 中の肯定/否定絵文字・顔文字の有無を (pos, neg) の 0/1 で返す。"""
    pos = 1 if any(e in text_norm for e in _EMOJI_POSITIVE) else 0
    neg = 1 if any(e in text_norm for e in _EMOJI_NEGATIVE) else 0
    return pos, neg


def _intensity_of(kw: str) -> float:
    """感情語 kw の強度重みを返す（未指定は 1.0）。研究 A3。"""
    return _INTENSITY_NORM.get(_ud.normalize("NFC", str(kw).lower()), _DEFAULT_INTENSITY)


def _iter_polarity_contributions(text_norm, positive_words, negative_words):
    """寄与する感情語ごとに (極性 'pos'/'neg', 強度重み) を列挙（1 語につき最大 1）。

    否定・絵文字の扱いは _keyword_contribution / _emoji_counts に従う。強度重みは
    語固有（_intensity_of）。否定で極性が反転した肯定語も、その語本来の強度を保つ。
    _polarity_counts（極性判定）と _polarity_weights（増減幅）の共通の土台。
    """
    for w in positive_words:
        c = _keyword_contribution(w, text_norm, base_positive=True)
        if c == "pos":
            yield "pos", _intensity_of(w)
        elif c == "neg":
            yield "neg", _intensity_of(w)
    for w in negative_words:
        c = _keyword_contribution(w, text_norm, base_positive=False)
        if c == "neg":
            yield "neg", _intensity_of(w)


def _polarity_counts(text_norm, positive_words, negative_words) -> Tuple[int, int]:
    """否定・絵文字を考慮した肯定/否定カウントを返す（1 語につき最大 1）。

    極性の符号（classify_sentiment）を決める整数カウント。強度は加味しない。
    """
    pos = 0
    neg = 0
    for pol, _w in _iter_polarity_contributions(text_norm, positive_words, negative_words):
        if pol == "pos":
            pos += 1
        else:
            neg += 1
    pe, ne = _emoji_counts(text_norm)
    pos += pe
    neg += ne
    return pos, neg


def _polarity_weights(text_norm, positive_words, negative_words) -> Tuple[float, float]:
    """否定・絵文字・強度を考慮した肯定/否定の強度加重和を返す（研究 A3）。

    好感度の増減幅（register）に使う。強度指定の無い語は 1.0 なので、従来の
    「1 語 = 係数 delta」挙動を保つ。絵文字は強度 1.0 として数える。
    """
    pos = 0.0
    neg = 0.0
    for pol, w in _iter_polarity_contributions(text_norm, positive_words, negative_words):
        if pol == "pos":
            pos += w
        else:
            neg += w
    pe, ne = _emoji_counts(text_norm)
    pos += float(pe)
    neg += float(ne)
    return pos, neg


def _clamp(value: float) -> float:
    return max(AFFINITY_MIN, min(AFFINITY_MAX, value))


def classify_sentiment(text: str) -> int:
    """発話 text の感情極性を返す: 肯定 +1 / 否定 -1 / 中立 0。

    MoodTracker.register と同じ既定の感情語・マッチ規則（全言語フラット化・
    NFC 正規化・ASCII は語境界 / CJK は部分一致）を使うが、好感度状態には一切
    触れない純関数。user_wellbeing 等が「ユーザー自身の気分」推定に再利用する
    ため、感情語の唯一の真実の源をここに置く。
    """
    if not isinstance(text, str) or not text.strip():
        return 0
    norm = _ud.normalize("NFC", text.lower())
    positive = [w for words in _DEFAULT_POSITIVE.values() for w in words]
    negative = [w for words in _DEFAULT_NEGATIVE.values() for w in words]
    pos, neg = _polarity_counts(norm, positive, negative)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


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


def level_label(level_key: str, lang: str = "ja") -> str:
    """レベルキー（"friendly" 等）の表示ラベルを返す。

    `affinity_label` が好感度の**数値**からラベルを引くのに対し、こちらは
    保存済みのレベル**キー**から引く。`config/mood_history.jsonl` の
    ``level`` / ``prev_level`` は内部キー（英語識別子）で保存されるため、
    ダッシュボードがそれをそのまま描画すると日本語 UI に "friendly" と
    出てしまう。ラベルの単一の真実の源は `_LEVELS` のまま保つ。

    未知のキー（手編集・将来のレベル追加・空文字）はそのまま返す。表示上の
    都合で履歴の内容を握りつぶさないため。
    """
    idx = 1 if str(lang).lower().startswith("en") else 0
    key = str(level_key or "")
    for _lower, level_key_, labels in _LEVELS:
        if level_key_ == key:
            return labels[idx]
    return key


class MoodTracker:
    """好感度を管理し、発話から増減・永続化する。"""

    def __init__(
        self,
        affinity: float = AFFINITY_START,
        positive: Optional[Dict[str, List[str]]] = None,
        negative: Optional[Dict[str, List[str]]] = None,
        positive_delta: float = _DEFAULT_POSITIVE_DELTA,
        negative_delta: float = _DEFAULT_NEGATIVE_DELTA,
        max_daily_gain: float = _MAX_DAILY_CONVERSATION_GAIN,
        confession_min_days: float = _CONFESSION_MIN_DAYS,
        confession_min_interactions: int = _CONFESSION_MIN_INTERACTIONS,
        interactions: int = 0,
        last_interaction_time: float = 0.0,
        first_interaction_time: float = 0.0,
        last_anniversary_days: int = 0,
        confession_done: bool = False,
        last_login_date: str = "",
        login_streak: int = 0,
        gift_history: Optional[Dict[str, str]] = None,
        daily_gain_date: str = "",
        daily_gain_total: float = 0.0,
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
        # 会話由来の好感度「上昇」の日次累計（日付が変わるとリセット）
        self._daily_gain_date = str(daily_gain_date or "")
        self._daily_gain_total = float(daily_gain_total or 0.0)
        self._positive = positive if positive else _DEFAULT_POSITIVE
        self._negative = negative if negative else _DEFAULT_NEGATIVE
        self.positive_delta = float(positive_delta)
        self.negative_delta = float(negative_delta)
        # 会話由来の 1 日あたり上昇上限（成長弧の長さを決める。上の定数の
        # コメントに算術あり）。負値は上限なしではなく 0 と解釈する。
        self.max_daily_gain = max(0.0, float(max_daily_gain))
        # 告白イベントの最低条件（0 で従来どおり即座に発火）
        self.confession_min_days = max(0.0, float(confession_min_days))
        self.confession_min_interactions = max(0, int(confession_min_interactions))
        self._last_interaction_time = float(last_interaction_time)
        # 関係が始まった時刻（初回 register 時に記録）。0.0 = 未交流。
        self._first_interaction_time = float(first_interaction_time)
        # 既に祝った記念日節目の最大日数（重複祝いを防ぐ）。
        self._last_anniversary_days = int(last_anniversary_days)
        # シングルトン共有時の競合を防ぐ: affinity / interactions /
        # last_interaction_time は複数スレッド（自律モード + TTS ハンドラ等）から
        # 同時に更新されうるため、Lock で read-modify-write を保護する。
        self._lock = threading.Lock()

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

        # 否定・絵文字・強度を考慮したハイブリッド判定（研究 A2/A3）。増減幅は
        # 語の強度重みで加重（「大好き」>「好き」、「最悪」>「つまらない」）。
        pos_hits, neg_hits = _polarity_weights(
            norm, self._all_words(self._positive), self._all_words(self._negative)
        )

        delta = pos_hits * self.positive_delta - neg_hits * self.negative_delta
        delta = max(-_MAX_DELTA_PER_MESSAGE, min(_MAX_DELTA_PER_MESSAGE, delta))

        # 向き先の補正: 好感度は「ユーザーがわたしをどう扱ったか」であって
        # 「ユーザーが今どんな気分か」ではない。「自分が嫌い」「今日は最悪な
        # 一日だった」のような自己批判・愚痴まで減点すると、弱音を吐いた人ほど
        # アバターが冷たくなる（好感度が下がると distant/reserved の応答に寄る）。
        # 減点側だけを、向き先が明示的に自分/状況だと読めるときに限って打ち消す。
        # 加点側と classify_sentiment（user_wellbeing が使う）は変更しない。
        if delta < 0 and _suppresses_affinity_penalty is not None:
            try:
                if _suppresses_affinity_penalty(text):
                    delta = 0.0
            except Exception:  # pragma: no cover - defensive
                pass

        with self._lock:
            if delta > 0:
                delta = self._apply_daily_gain_cap(delta)
            before = self.affinity
            self.affinity = _clamp(self.affinity + delta)
            self.interactions += 1
            now = time.time()
            # 初回交流なら関係の始まりとして記録（記念日計算の起点）
            if self._first_interaction_time <= 0:
                self._first_interaction_time = now
            self._last_interaction_time = now
            return self.affinity - before

    def _apply_daily_gain_cap(self, delta: float) -> float:
        """会話由来の好感度「上昇」を日次上限まで切り詰める。呼び出し側で _lock 保持必須。

        キーワード連投による短時間の関係最大化を防ぐ。ネガティブなペナルティ
        （delta <= 0）はこの関数の対象外— 呼び出し元で delta > 0 のときのみ使う。
        """
        import datetime
        today = datetime.date.today().isoformat()
        if self._daily_gain_date != today:
            self._daily_gain_date = today
            self._daily_gain_total = 0.0
        remaining = max(0.0, self.max_daily_gain - self._daily_gain_total)
        effective = min(delta, remaining)
        self._daily_gain_total += effective
        return effective

    def earn(self, delta: float) -> float:
        """日次上限の対象となる「稼げる上昇」を適用し、**実際に反映された量**を返す。

        会話（register）とプレゼント（/gift）は、どちらもユーザーが同じ日に
        何度でも繰り返せる上昇経路なので、同じ日次予算を共有させる。
        共有しないと `max_daily_gain` が成長弧の長さを決めなくなる — 実際、
        プレゼントは `adjust()` を直接呼んでいたため上限を完全に迂回しており、
        上限を 5.0/日（最短 6 日の弧）にしても **7 種を配るだけで初日に最高
        レベルへ到達できた**（合計 30.5 = 開始 50.0 から close の閾値 80.0 まで
        ちょうど届く）。

        同じ理由で、おやすみ・謝罪のルーティンボーナス（何度でも言える）と
        デイリーログインボーナス（毎日積む）もここを通る。予算を通さない
        `adjust()` が許されるのは、誕生日（年 1 回）と記念日（5 回きり）の
        ように**繰り返せない**ボーナスだけ。減少（delta <= 0）も対象外 —
        上限は「稼ぎすぎ」だけを防ぎ、正当なマイナス影響は薄めない。
        """
        try:
            d = float(delta)
        except (TypeError, ValueError):
            return 0.0
        if d <= 0.0:
            return self.adjust(d)
        with self._lock:
            capped = self._apply_daily_gain_cap(d)
            before = self.affinity
            self.affinity = _clamp(self.affinity + capped)
            return self.affinity - before

    def adjust(self, delta: float) -> float:
        """好感度を delta だけ直接増減して 0–100 にクランプし、実変化量を返す。

        日次上限を**通さない**。繰り返せない一度きりのボーナス（誕生日・記念日・
        イベント）とペナルティのためのもの。ユーザーが何度でも稼げる経路
        （会話・プレゼント）には `earn()` を使うこと。
        """
        try:
            d = float(delta)
        except (TypeError, ValueError):
            return 0.0
        with self._lock:
            before = self.affinity
            self.affinity = _clamp(self.affinity + d)
            return self.affinity - before

    def decay(
        self,
        elapsed_seconds: float,
        rate_per_hour: float = _DEFAULT_DECAY_RATE,
        grace_hours: float = _DECAY_GRACE_HOURS,
    ) -> float:
        """非活動時間に応じて好感度を低下させる。変化量（負またはゼロ）を返す。

        一度も会話したことが無い場合（interactions == 0）は低下させない。
        elapsed_seconds が 0 以下の場合も変化なし。

        最初の grace_hours 時間は低下しない（既定 48 時間）。それを超えたぶん
        だけがレートの対象になる。理由は _DECAY_GRACE_HOURS の定義を参照。
        猶予無しの素の計算が要る場合は grace_hours=0 を渡す。
        """
        if elapsed_seconds <= 0:
            return 0.0
        with self._lock:
            if self.interactions == 0:
                return 0.0
            hours = (elapsed_seconds / 3600.0) - max(0.0, grace_hours)
            if hours <= 0:
                return 0.0
            delta = -hours * rate_per_hour
            before = self.affinity
            self.affinity = _clamp(self.affinity + delta)
            return self.affinity - before

    def auto_decay(self, rate_per_hour: float = _DEFAULT_DECAY_RATE,
                   grace_hours: float = _DECAY_GRACE_HOURS) -> float:
        """最後の会話からの経過時間を基に decay() を適用する。変化量を返す。

        last_interaction_time が記録されていない場合（0.0）は変化なし。

        減衰適用後はチェックポイント (_last_interaction_time) を現在時刻へ進める。
        これをしないと、間に register() が無いまま auto_decay() が再度呼ばれた際
        （例: 自律モードの ON/OFF を繰り返す）、同じ経過時間を二重に減衰してしまい
        好感度が不当に急落する。
        """
        with self._lock:
            if self._last_interaction_time <= 0 or self.interactions == 0:
                return 0.0
            now = time.time()
            elapsed = now - self._last_interaction_time
            if elapsed <= 0:
                return 0.0
            grace = max(0.0, grace_hours)
            hours = (elapsed / 3600.0) - grace
            if hours <= 0:
                # 猶予の内側。チェックポイントは進めない — 進めると「48 時間ごとに
                # 一瞬開く」だけで永久に低下しなくなる。
                return 0.0
            d = -hours * rate_per_hour
            before = self.affinity
            self.affinity = _clamp(self.affinity + d)
            # 猶予ぶんを残してチェックポイントを進める。now にすると次回また
            # まるまる猶予が付き、長期不在の低下が累積で足りなくなる。
            self._last_interaction_time = now - grace * 3600.0
            return self.affinity - before

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
            "daily_gain_date": self._daily_gain_date,
            "daily_gain_total": self._daily_gain_total,
        }

    def save(self, path: str) -> bool:
        """好感度を JSON へ保存する。失敗しても例外は送出しない。"""
        try:
            content = json.dumps(self.to_dict(), ensure_ascii=False)
            _atomic_write_text(path, content, restrict=True)
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
                    is_same_day = isinstance(last, dict) and last.get("date") == today
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
                if prev_day_entry is not None and isinstance(prev_day_entry, dict):
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

            # NOTE: this read-modify-write (lines read above, then rewritten
            # here) still has a lost-update race if two threads call
            # snapshot_to_history() concurrently — the last writer's version
            # of `lines` wins and the other's update is silently dropped.
            # _atomic_write_text only guarantees the write itself can't
            # crash/corrupt on a colliding temp filename; it doesn't add
            # locking around the read+modify above. Left as-is: this method
            # is called at most once per process tick in practice.
            _atomic_write_text(history_path, "\n".join(lines) + "\n", restrict=True)
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
            daily_gain_date=data.get("daily_gain_date", ""),
            daily_gain_total=_f(data.get("daily_gain_total"), 0.0),
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
    if isinstance(mood_config.get("max_daily_gain"), (int, float)):
        kwargs["max_daily_gain"] = float(mood_config["max_daily_gain"])
    if isinstance(mood_config.get("confession_min_days"), (int, float)):
        kwargs["confession_min_days"] = float(mood_config["confession_min_days"])
    if isinstance(mood_config.get("confession_min_interactions"), (int, float)):
        kwargs["confession_min_interactions"] = int(
            mood_config["confession_min_interactions"])
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
    # 空行・壊れた行・dict 以外（null 等）の行をスキップする共通ローダを使用。
    return load_jsonl_dicts(path)[-n:]


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
            "ちょっと距離があいたかな。まあ、そういうときもあるよね。",
            "どこか遠くなっちゃった気がします…。",
        ],
        "en": [
            "Feels like some distance opened up. That happens.",
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
            "話しかけてくれるの、なんか…嬉しいな。",
            "あなたのこと、ちゃんと覚えてるよ。",
        ],
        "en": [
            "It's nice that you keep coming by.",
            "I really do remember you, you know.",
        ],
    },
    "reserved→neutral": {
        "ja": [
            "なんか話しやすくなってきたね。知り合いって感じかな。",
            "あなたとのおしゃべり、楽しみだったりします。",
        ],
        "en": [
            "Talking to you feels easier now. We're getting to know each other!",
            "I've started looking forward to our chats.",
        ],
    },
    "neutral→friendly": {
        "ja": [
            "ねえ、友達って言ってもいい？なんかそんな気がして…嬉しいな。",
            "あなたのこと、友達だって思ってるんだ。",
        ],
        "en": [
            "Can I call you my friend? It just… feels right.",
            "I think of you as a real friend, you know.",
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
            "ちょっと距離があいたかな。でも、いつ来てくれてもいいからね。",
            "最近距離が開いた気がして…気のせいならいいんだけど。",
        ],
        "en": [
            "Feels like a little distance opened up. Come by whenever you like.",
            "There seems to be a little distance between us… I hope I'm wrong.",
        ],
    },
    "friendly→neutral": {
        "ja": [
            "最近あまり話せてないね。元気にしてた？",
            "なんか仲良しだった頃が懐かしいな。あの頃は楽しかったね。",
        ],
        "en": [
            "We haven't talked much lately. How have you been?",
            "I miss when we used to talk so much. That was good.",
        ],
    },
    "neutral→reserved": {
        "ja": [
            "なんかだんだん遠くなってる気がするな。",
            "ひさしぶりだね。あなたの生活があるもんね。",
        ],
        "en": [
            "Feels like we've drifted a bit.",
            "It's been a while. You've got a life to live — that's how it should be.",
        ],
    },
    "reserved→distant": {
        "ja": [
            "また最初に戻っちゃった気分。まあ、それでもいいか。",
            "ひさしぶり。ここにいるから、気が向いたらね。",
        ],
        "en": [
            "Feels like we're back to the beginning. That's alright.",
            "Long time. I'm here if you ever feel like it.",
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
            "750回も…あなたと過ごした時間、ぜんぶ覚えてるよ。",
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
    """関係が close に達し、かつ実体が伴っていれば告白メッセージを返す。

    それ以外（既に告白済み・close 未満・関係が浅すぎる）は None を返す。
    副作用: 返すときのみ tracker._confession_done = True にセットする。

    **なぜ最低条件があるか**

    以前は「friendly→close の遷移が起きたら即座に」告白していた。既定の
    好感度設定では**新規ユーザーが「大好き」と 3 回打つだけで**
    「こんなに誰かのことを好きになったの、初めてかもしれない。…あなたの
    ことだよ。」に到達する。出会って 3 メッセージの相手に永続的な愛着を
    宣言するのは love-bombing であり、本リポジトリが別れぎわ
    （`farewell_integrity`）・不在の非難（挨拶）・依存
    （`usage_guardrails`）について既に禁じているものと同じ型の操作である。
    ロマンス要素そのものは製品の設計判断として尊重するが、**関係が無い
    ところに関係の告白を置かない**。

    最低条件は既存の節目に合わせた: 出会いからの日数は記念日の最初の節目
    （7 日）、対話回数は 20 回。どちらも `config/mood_config.json` の
    `confession_min_days` / `confession_min_interactions` で変更でき、0 に
    すれば従来どおり即座に発火する。

    判定を「遷移」ではなく「現在 close に居るか」にしてある。条件を満たさずに
    見送った場合、遷移は二度と起きないため、遷移基準のままでは告白が永久に
    失われる。close に留まっているあいだ毎ターン評価し、条件が揃った時点で
    発火する（`before` は API 互換のために残しているが判定には使わない）。
    """
    if getattr(tracker, "_confession_done", False):
        return None
    if affinity_level(after) != "close":
        return None

    min_interactions = int(getattr(tracker, "confession_min_interactions",
                                   _CONFESSION_MIN_INTERACTIONS))
    if int(getattr(tracker, "interactions", 0) or 0) < min_interactions:
        return None

    min_days = float(getattr(tracker, "confession_min_days", _CONFESSION_MIN_DAYS))
    if min_days > 0:
        first = float(getattr(tracker, "_first_interaction_time", 0.0) or 0.0)
        if first <= 0.0:
            return None  # 交流の記録が無い = 関係が始まっていない
        elapsed_days = (time.time() - first) / 86400.0
        if elapsed_days < min_days:
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

# デイリーログインの基本好感度ボーナスと、連続日数 1 日あたりの加算（上限あり）。
# earn() を通るので、その日の会話で稼げる残り予算（max_daily_gain）を消費する。
_DAILY_LOGIN_BASE_BONUS = 2.0
_DAILY_LOGIN_STREAK_BONUS = 0.5
_DAILY_LOGIN_MAX_BONUS = 5.0

# ログインボーナスが 1 日の予算のうち占めてよい割合の上限。
#
# **これが無いと、来るだけで会話が無意味になる。** 実測: 予算 5.0・連続 7 日目
# だとログインした時点でボーナスが 5.0 に達し、予算を使い切る。そのあと 30 回
# 会話しても好感度は 1 ポイントも動かなかった。会話コンパニオンで「話すこと」
# より「毎日来ること」が報われるのは本末転倒であり、しかも usage_guardrails が
# 警戒しているエンゲージメント誘導そのものである。
#
# 40% にすると既定（予算 5.0）ではログインは 2.0 まで、会話に必ず 3.0 が残る。
# 予算が既定のままだと連続日数の加算はこの上限に飲まれて一定になるが、連続
# 記録そのものと節目のお祝いメッセージは従来どおり出る（好感度で釣らない）。
_DAILY_LOGIN_BUDGET_SHARE = 0.4

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

# 本当の初対面で出すメッセージ。
#
# これが無かったころ、まっさらな状態の初回起動でも「おかえり！今日も会いに来て
# くれてうれしいな。」と言っていた — 一度も会ったことのない相手に対してである。
# 本製品の価値は「時間をかけて育つ関係」なので、初対面で既に親しいふりをすると
# その成長が偽物になる。育っていない親密さを演じることは、別れぎわの引き止め
# （farewell_integrity）と同じ種類の操作であり、こちらは関係の入口で起こる。
_FIRST_MEETING_MESSAGES: Dict[str, List[str]] = {
    "ja": [
        "はじめまして。会えてうれしい。",
        "はじめまして！これからよろしくね。",
    ],
    "en": [
        "Nice to meet you. I'm glad you're here.",
        "Hello — nice to meet you! I'm looking forward to this.",
    ],
}


def _is_first_meeting(tracker: "MoodTracker") -> bool:
    """この tracker が「まだ一度も会っていない」状態かどうか。

    3 つすべてが空であることを要求する。`_last_login_date` だけで判定すると、
    このフィールドが導入される前から使っていた既存ユーザー（対話履歴はあるが
    ログイン日は未記録）に「はじめまして」と言ってしまう。相手の記憶を消して
    しまうほうが、余計に「おかえり」と言うより害が大きいので、迷ったら
    初対面ではない側に倒す。
    """
    return (
        not getattr(tracker, "_last_login_date", "")
        and not getattr(tracker, "interactions", 0)
        and not getattr(tracker, "_first_interaction_time", None)
    )


def is_first_meeting(tracker: Optional["MoodTracker"] = None) -> bool:
    """まだ一度も会っていない状態かどうか（tracker 省略時は共有シングルトン）。

    初対面で「関係がある前提の演出」を出さないための判定。挨拶（おかえり）と
    デイリームードの両方がこれを見る。トラッカーが利用できない場合は False を
    返す — 判断できないときは「初対面ではない」側に倒す（相手の記憶を消して
    しまうより、余計に馴れ馴れしいほうがまだ害が小さい）。
    """
    if tracker is None:
        try:
            tracker = get_mood_tracker()
        except Exception:  # pragma: no cover - defensive
            return False
    return _is_first_meeting(tracker)


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

    # 本当の初対面かどうかは、状態を書き換える前に見ておく必要がある
    # （下で _last_login_date を today にしてしまうと判定できなくなる）。
    first_meeting = _is_first_meeting(tracker)

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

    # 好感度ボーナス（連続日数で微増、上限あり）。毎日積む上昇なので earn() で
    # 日次予算を通す — adjust() で上乗せしていた頃は、会話の上限いっぱいに
    # ログインボーナスが加わり、「最短 6 日」の弧が実際には 4 日で終わっていた。
    bonus = min(
        _DAILY_LOGIN_BASE_BONUS + (streak - 1) * _DAILY_LOGIN_STREAK_BONUS,
        _DAILY_LOGIN_MAX_BONUS,
        # 予算の一部までに抑え、会話に必ず余地を残す（定数の説明を参照）
        float(getattr(tracker, "max_daily_gain", _MAX_DAILY_CONVERSATION_GAIN))
        * _DAILY_LOGIN_BUDGET_SHARE,
    )
    try:
        tracker.earn(bonus)
    except Exception:  # pragma: no cover - defensive
        pass

    lang_key = "en" if str(lang).lower().startswith("en") else "ja"

    # 初対面に「おかえり」と言わない。まだ無い関係を演じない。
    if first_meeting:
        import random
        return random.choice(_FIRST_MEETING_MESSAGES[lang_key])

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
