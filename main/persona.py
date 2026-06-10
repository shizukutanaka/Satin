"""
ペルソナ / 対話システム。

アバターの「名前」と状態別の台詞（talk / rest / 時刻別あいさつ）を、ソースコードを
書き換えずに ``config/persona.json`` で差し替えられるようにする。これまで各アバター
ビューア（avatar_3d_autonomous / _tts / autonomous_gltf_avatar など）が同一の
``self.talks`` 日本語フレーズ配列をハードコード重複していた問題を解消し、さらに
i18n と同様の言語フォールバックと時刻依存あいさつを追加する。

依存は標準ライブラリのみ。設定ファイルが無い/壊れていても安全な既定値で動作する。

設定ファイル例 (config/persona.json):
    {
      "name": "Satin",
      "default_lang": "ja",
      "dialogue": {
        "ja": {
          "talk": ["こんにちは！", "走るの大好き！"],
          "rest": ["ふう…ちょっと休憩。"],
          "greeting": {
            "morning":   ["おはよう！"],
            "afternoon": ["こんにちは！"],
            "evening":   ["こんばんは。"],
            "night":     ["こんな時間まで…おつかれさま。"]
          }
        },
        "en": { "talk": ["Hello!"], "rest": ["Phew, a little break."] }
      }
    }
"""
from __future__ import annotations

import json
import os
import random
import threading
from datetime import datetime
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# 既定値（設定ファイルが無くても従来挙動を維持できるフォールバック）
# --------------------------------------------------------------------------- #
_DEFAULT_NAME = "Satin"
_DEFAULT_LANG = "ja"

_DEFAULT_DIALOGUE: Dict[str, Dict] = {
    "ja": {
        "talk": [
            "こんにちは！",
            "今日はいい天気ですね。",
            "ちょっと休憩します…",
            "走るの大好き！",
            "あなたも一緒にどう？",
        ],
        "rest": ["ふう…ちょっと休憩。", "すこし止まります。"],
        "greeting": {
            "morning": ["おはよう！今日も一日がんばろう。"],
            "afternoon": ["こんにちは！調子はどう？"],
            "evening": ["こんばんは。おつかれさま。"],
            "night": ["こんな時間まで…無理しないでね。"],
        },
    },
    "en": {
        "talk": [
            "Hello!",
            "Nice weather today.",
            "Taking a little break...",
            "I love running around!",
            "Want to join me?",
        ],
        "rest": ["Phew, a short break.", "Stopping for a moment."],
        "greeting": {
            "morning": ["Good morning! Let's make today great."],
            "afternoon": ["Good afternoon! How are you?"],
            "evening": ["Good evening. Nice to see you."],
            "night": ["It's late... don't push yourself too hard."],
        },
    },
}


def _time_of_day(hour: int) -> str:
    """時刻(0-23)を morning / afternoon / evening / night に区分する。"""
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


class Persona:
    """アバターの名前と状態別台詞を保持し、台詞を選択するクラス。

    台詞選択は直前に返したものを避ける（``random.choice`` だと同じ台詞が連続
    しうるのを防ぐ）。言語は i18n と同じく要求言語→default_lang→en→任意の順で
    フォールバックする。
    """

    def __init__(
        self,
        name: str = _DEFAULT_NAME,
        dialogue: Optional[Dict[str, Dict]] = None,
        default_lang: str = _DEFAULT_LANG,
        lang: Optional[str] = None,
    ):
        self.name = name or _DEFAULT_NAME
        self.default_lang = default_lang or _DEFAULT_LANG
        self._dialogue = dialogue if dialogue else _DEFAULT_DIALOGUE
        self.lang = (lang or self.default_lang).lower()
        # カテゴリごとに直前に返したインデックスを記録して連続を避ける
        self._last: Dict[str, str] = {}

    # ---- 言語解決 -------------------------------------------------------- #
    def _resolve_lang_block(self, lang: Optional[str] = None) -> Dict:
        """要求言語の dialogue ブロックを、フォールバックを辿って返す。"""
        candidates: List[str] = []
        if lang:
            candidates.append(lang.lower())
            # "en-us" → "en" のような地域コードも試す
            if "-" in lang:
                candidates.append(lang.lower().split("-")[0])
        candidates.append(self.lang)
        candidates.append(self.default_lang)
        candidates.append("en")
        for cand in candidates:
            block = self._dialogue.get(cand)
            if block:
                return block
        # どれも無ければ任意の最初のブロック、それも無ければ空
        for block in self._dialogue.values():
            if block:
                return block
        return {}

    # ---- 台詞選択 -------------------------------------------------------- #
    def _pick(self, category_key: str, options: List[str]) -> str:
        """options から直前と異なるものを 1 つ選ぶ。空なら空文字。"""
        if not options:
            return ""
        if len(options) == 1:
            self._last[category_key] = options[0]
            return options[0]
        last = self._last.get(category_key)
        choice = random.choice(options)
        # 直前と同じなら 1 回だけ引き直す（無限ループを避けるため再帰しない）
        if choice == last:
            remaining = [o for o in options if o != last]
            if remaining:
                choice = random.choice(remaining)
        self._last[category_key] = choice
        return choice

    def talk(self, lang: Optional[str] = None) -> str:
        """雑談台詞を 1 つ返す。"""
        block = self._resolve_lang_block(lang)
        return self._pick(f"talk:{lang or self.lang}", list(block.get("talk", [])))

    def rest(self, lang: Optional[str] = None) -> str:
        """休憩台詞を 1 つ返す。"""
        block = self._resolve_lang_block(lang)
        return self._pick(f"rest:{lang or self.lang}", list(block.get("rest", [])))

    def greeting(self, lang: Optional[str] = None, now: Optional[datetime] = None) -> str:
        """時刻に応じたあいさつを 1 つ返す。greeting 未定義なら talk にフォールバック。"""
        block = self._resolve_lang_block(lang)
        greetings = block.get("greeting") or {}
        slot = _time_of_day((now or datetime.now()).hour)
        options = list(greetings.get(slot, []))
        if not options:
            # 時間帯が無ければ任意のあいさつ、それも無ければ雑談
            for vals in greetings.values():
                if vals:
                    options = list(vals)
                    break
        if not options:
            return self.talk(lang)
        return self._pick(f"greeting:{slot}:{lang or self.lang}", options)

    # ---- 構築 ------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: Dict, lang: Optional[str] = None) -> "Persona":
        """辞書（config/persona.json の中身）から Persona を構築する。"""
        if not isinstance(data, dict):
            data = {}
        dialogue = data.get("dialogue")
        if not isinstance(dialogue, dict) or not dialogue:
            dialogue = None
        return cls(
            name=data.get("name", _DEFAULT_NAME),
            dialogue=dialogue,
            default_lang=data.get("default_lang", _DEFAULT_LANG),
            lang=lang,
        )

    @classmethod
    def load(cls, config_path: Optional[str] = None, lang: Optional[str] = None) -> "Persona":
        """config/persona.json を読み込んで Persona を構築する。

        ファイルが無い/壊れている場合は既定ペルソナを返す（例外は送出しない）。
        言語が未指定なら SATIN_LANG 環境変数を参照する。
        """
        if lang is None:
            lang = os.environ.get("SATIN_LANG")
        path = config_path or _default_persona_path()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return cls.from_dict(data, lang=lang)
            except Exception:  # pragma: no cover - defensive: 壊れた設定でも既定で動く
                pass
        return cls(lang=lang)


def _default_persona_path() -> Optional[str]:
    """既定の persona.json パスを解決する（リポジトリ root の config/ を優先）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "config", "persona.json"),          # main/config/persona.json
        os.path.join(os.path.dirname(here), "config", "persona.json"),  # <repo>/config/persona.json
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[-1]


# --------------------------------------------------------------------------- #
# プロセス内シングルトン（全アバタービューアで共有）
# --------------------------------------------------------------------------- #
_persona_singleton: Optional[Persona] = None
_persona_lock = threading.Lock()


def get_persona(lang: Optional[str] = None) -> Persona:
    """共有 Persona インスタンスを返す（初回のみ config から読み込む）。"""
    global _persona_singleton
    if _persona_singleton is None:
        with _persona_lock:
            if _persona_singleton is None:
                _persona_singleton = Persona.load(lang=lang)
    return _persona_singleton


def reset_persona() -> None:
    """シングルトンを破棄する（設定再読み込み・テスト用）。"""
    global _persona_singleton
    with _persona_lock:
        _persona_singleton = None
