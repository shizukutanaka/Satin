"""
ユーザープロファイル（アバターがユーザーを覚えるための最小限の記憶）。

これまでアバターは好感度（関係の深さ）は覚えても、相手が「誰か」は一切覚えなかった。
follow_up_question() で「あなたの名前は？」と聞けても答えを保持できず、毎回はじめまして
状態になっていた。本モジュールはユーザーの呼び名（と任意のメモ）を JSON に永続化し、
あいさつや応答で名前を使えるようにする。

保存先は config/user_profile.json（mood.json と同じく個人データなので gitignore 済み）。
記録の失敗は呼び出し元の UI/TTS を壊さないよう必ず握り潰す。依存は標準ライブラリのみ。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Dict, List, Optional

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

# 名前が長すぎる/制御文字を含む入力を弾くための上限
_MAX_NAME_LEN = 40
# 保持する趣味・興味の最大件数
_MAX_INTERESTS = 10
# 1件あたりの趣味テキストの最大文字数
_MAX_INTEREST_LEN = 30
# 「一問一答」で覚える事実の上限件数と 1 件あたりの最大文字数
_MAX_FACTS = 20
_MAX_FACT_LEN = 60

# 名前が未設定のときの中立的な呼びかけ（{user} プレースホルダのフォールバック）
_NEUTRAL_ADDRESS = {"ja": "きみ", "en": "you"}


def _sanitize_birthday(s: Optional[str]) -> str:
    """誕生日を ``MM-DD`` 正規形へ整える。不正なら空文字。

    ``MM-DD`` / ``MM/DD``（1〜2 桁）を受け付け、実在する日付かを検証する
    （2 月 29 日も許可）。曜日や年は持たない（毎年巡る日付として扱う）。
    """
    if not s:
        return ""
    import re
    text = str(s).strip().replace("/", "-")
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", text)
    if not m:
        return ""
    month, day = int(m.group(1)), int(m.group(2))
    try:
        import datetime
        datetime.date(2000, month, day)  # 2000 はうるう年: 02-29 を許可
    except ValueError:
        return ""
    return f"{month:02d}-{day:02d}"


def _sanitize_name(name: Optional[str]) -> str:
    """ユーザー名を安全な 1 行文字列へ整える。

    前後空白を除去し、改行・制御文字を空白へ畳み込み、長すぎる場合は切り詰める。
    None/空なら空文字を返す。
    """
    if not name:
        return ""
    s = str(name).replace("\r", " ").replace("\n", " ").strip()
    # 制御文字（タブ等）を空白に置換
    s = "".join(ch if ch.isprintable() else " " for ch in s).strip()
    if len(s) > _MAX_NAME_LEN:
        s = s[:_MAX_NAME_LEN].strip()
    return s


def _sanitize_interest(text: Optional[str]) -> str:
    """趣味テキストを安全な 1 行文字列へ整える。空/長すぎる場合は空文字。"""
    if not text:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").strip()
    s = "".join(ch if ch.isprintable() else " " for ch in s).strip()
    if not s or len(s) > _MAX_INTEREST_LEN:
        return ""
    return s


def _sanitize_fact(text: Optional[str], max_len: int = _MAX_FACT_LEN) -> str:
    """一問一答の回答テキストを安全な 1 行文字列へ整える。

    前後空白除去・制御文字畳み込みのうえ、長すぎる場合は切り詰める
    （趣味と違い回答は捨てずに切り詰めて保持する）。空なら空文字。
    """
    if not text:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").strip()
    s = "".join(ch if ch.isprintable() else " " for ch in s).strip()
    if not s:
        return ""
    if len(s) > max_len:
        s = s[:max_len].strip()
    return s


class UserProfile:
    """ユーザーの呼び名と任意メモを保持・永続化するクラス。"""

    def __init__(self, name: str = "", note: str = "",
                 birthday: str = "", last_birthday_year: int = 0,
                 interests: Optional[List[str]] = None,
                 facts: Optional[Dict[str, str]] = None):
        self.name = _sanitize_name(name)
        self.note = _sanitize_name(note)
        # 誕生日（MM-DD、毎年巡る）と、最後に祝った年（重複祝い防止）
        self.birthday = _sanitize_birthday(birthday)
        self._last_birthday_year = int(last_birthday_year or 0)
        # 趣味・好きなものリスト（最大 _MAX_INTERESTS 件）
        self.interests: List[str] = []
        for item in (interests or []):
            s = _sanitize_interest(item)
            if s and s not in self.interests:
                self.interests.append(s)
        self.interests = self.interests[:_MAX_INTERESTS]
        # 一問一答で覚えた事実（key → 回答テキスト。最大 _MAX_FACTS 件）
        self.facts: Dict[str, str] = {}
        if isinstance(facts, dict):
            for key, value in facts.items():
                if len(self.facts) >= _MAX_FACTS:
                    break
                k = _sanitize_interest(key)  # キーも 1 行・短文に正規化
                v = _sanitize_fact(value)
                if k and v:
                    self.facts[k] = v

    # ---- 状態参照 -------------------------------------------------------- #
    def has_name(self) -> bool:
        return bool(self.name)

    def has_birthday(self) -> bool:
        return bool(self.birthday)

    def has_interests(self) -> bool:
        return bool(self.interests)

    def has_fact(self, key: str) -> bool:
        return bool(self.facts.get(_sanitize_interest(key)))

    def get_fact(self, key: str) -> str:
        """覚えた事実を返す。未知なら空文字。"""
        return self.facts.get(_sanitize_interest(key), "")

    def address(self, lang: str = "ja") -> str:
        """呼びかけに使う文字列を返す。名前未設定なら中立的な代名詞。"""
        if self.name:
            return self.name
        key = "en" if str(lang).lower().startswith("en") else "ja"
        return _NEUTRAL_ADDRESS[key]

    # ---- 更新 ------------------------------------------------------------ #
    def set_name(self, name: str) -> str:
        """呼び名を設定し、整形後の値を返す。"""
        self.name = _sanitize_name(name)
        return self.name

    def set_birthday(self, birthday: str) -> str:
        """誕生日を設定し、整形後の値（MM-DD）を返す。不正なら空文字。"""
        new = _sanitize_birthday(birthday)
        if new != self.birthday:
            # 誕生日を変えたら「今年祝った」フラグもリセット（再度祝えるように）
            self._last_birthday_year = 0
        self.birthday = new
        return self.birthday

    def add_interest(self, text: str) -> str:
        """趣味を追加する。整形後の値を返す（無効なら空文字、上限超えでも空文字）。"""
        s = _sanitize_interest(text)
        if not s:
            return ""
        if s in self.interests:
            return s
        if len(self.interests) >= _MAX_INTERESTS:
            return ""
        self.interests.append(s)
        return s

    def remove_interest(self, text: str) -> bool:
        """趣味を削除する。見つかれば True。"""
        s = _sanitize_interest(text)
        if s and s in self.interests:
            self.interests.remove(s)
            return True
        return False

    def set_fact(self, key: str, value: str) -> str:
        """一問一答で得た事実を保存する。整形後の値を返す（無効なら空文字）。

        既知キーの上書きは常に許可する。新規キーは上限 _MAX_FACTS まで。
        """
        k = _sanitize_interest(key)
        v = _sanitize_fact(value)
        if not k or not v:
            return ""
        if k not in self.facts and len(self.facts) >= _MAX_FACTS:
            return ""
        self.facts[k] = v
        return v

    def remove_fact(self, key: str) -> bool:
        """覚えた事実を削除する。見つかれば True。"""
        k = _sanitize_interest(key)
        if k in self.facts:
            del self.facts[k]
            return True
        return False

    def clear(self) -> None:
        """プロファイルを空にする（メモリ上のみ。削除は呼び出し側で）。"""
        self.name = ""
        self.note = ""
        self.birthday = ""
        self._last_birthday_year = 0
        self.interests = []
        self.facts = {}

    # ---- 永続化 ---------------------------------------------------------- #
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "note": self.note,
            "birthday": self.birthday,
            "last_birthday_year": self._last_birthday_year,
            "interests": list(self.interests),
            "facts": dict(self.facts),
        }

    def save(self, path: str) -> bool:
        """プロファイルを JSON へ保存する。失敗しても例外は送出しない。"""
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
            logger.warning("ユーザープロファイルの保存に失敗しました: %s", e)
            return False

    @classmethod
    def from_dict(cls, data: Dict) -> "UserProfile":
        if not isinstance(data, dict):
            data = {}
        raw_interests = data.get("interests", [])
        interests = raw_interests if isinstance(raw_interests, list) else []
        raw_facts = data.get("facts", {})
        facts = raw_facts if isinstance(raw_facts, dict) else {}
        return cls(
            name=data.get("name", ""),
            note=data.get("note", ""),
            birthday=data.get("birthday", ""),
            last_birthday_year=data.get("last_birthday_year", 0),
            interests=interests,
            facts=facts,
        )

    @classmethod
    def load(cls, path: Optional[str] = None) -> "UserProfile":
        """保存済みプロファイルを読み込む。無ければ空で開始。壊れていれば既定。"""
        p = path or _default_profile_path()
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return cls.from_dict(json.load(f))
            except Exception:  # pragma: no cover - defensive
                logger.warning("ユーザープロファイルの読み込みに失敗。空で開始します。")
        return cls()


def _default_profile_path() -> str:
    """既定のプロファイル保存先（リポジトリ root の config/user_profile.json）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "user_profile.json")


def personalize(text: str, profile: "Optional[UserProfile]", lang: str = "ja") -> str:
    """text 中の ``{user}`` プレースホルダをユーザーの呼び名へ置換する。

    profile が None / 名前未設定でも中立的な代名詞でフォールバックするため、
    どんな台詞でも安全に呼びかけを織り込める。プレースホルダが無ければ無変換。
    """
    if not text or "{user}" not in text:
        return text
    if profile is not None:
        addr = profile.address(lang)
    else:
        key = "en" if str(lang).lower().startswith("en") else "ja"
        addr = _NEUTRAL_ADDRESS[key]
    return text.replace("{user}", addr)


# --------------------------------------------------------------------------- #
# プロセス内シングルトン
# --------------------------------------------------------------------------- #
_profile_singleton: Optional[UserProfile] = None
_lock = threading.Lock()


def get_user_profile(path: Optional[str] = None) -> UserProfile:
    """共有 UserProfile を返す（初回に保存ファイルから読み込む）。"""
    global _profile_singleton
    if _profile_singleton is None:
        with _lock:
            if _profile_singleton is None:
                _profile_singleton = UserProfile.load(path)
    return _profile_singleton


def reset_user_profile() -> None:
    """シングルトンを破棄する（テスト・プロファイル切替用）。"""
    global _profile_singleton
    with _lock:
        _profile_singleton = None
