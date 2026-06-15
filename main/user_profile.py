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
from typing import Dict, Optional

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


class UserProfile:
    """ユーザーの呼び名と任意メモを保持・永続化するクラス。"""

    def __init__(self, name: str = "", note: str = "",
                 birthday: str = "", last_birthday_year: int = 0):
        self.name = _sanitize_name(name)
        self.note = _sanitize_name(note)
        # 誕生日（MM-DD、毎年巡る）と、最後に祝った年（重複祝い防止）
        self.birthday = _sanitize_birthday(birthday)
        self._last_birthday_year = int(last_birthday_year or 0)

    # ---- 状態参照 -------------------------------------------------------- #
    def has_name(self) -> bool:
        return bool(self.name)

    def has_birthday(self) -> bool:
        return bool(self.birthday)

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

    def clear(self) -> None:
        """プロファイルを空にする（メモリ上のみ。削除は呼び出し側で）。"""
        self.name = ""
        self.note = ""
        self.birthday = ""
        self._last_birthday_year = 0

    # ---- 永続化 ---------------------------------------------------------- #
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "note": self.note,
            "birthday": self.birthday,
            "last_birthday_year": self._last_birthday_year,
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
        return cls(
            name=data.get("name", ""),
            note=data.get("note", ""),
            birthday=data.get("birthday", ""),
            last_birthday_year=data.get("last_birthday_year", 0),
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
