"""コマンドの使い方表示が GUI と CLI でずれないこと。

同じアバターが同じコマンドについて説明しているのに、文言が割れていた:

    GUI: 「使い方: /birthday MM-DD  例: /birthday 03-14」
    CLI: 「使用方法: /birthday MM-DD （例: /birthday 06-15）」

見出し語が「使い方」と「使用方法」で違い、例に使う日付まで違っていた。同種の
ずれが 11 箇所あった（`/callme`・`/like`・`/forget`・`/forget-fact`・`/search`
ほか）。どちらが正しいという話ではなく、**2 箇所で手作業で同期する構造**が
必然的に生む劣化である。

定義を `persona_cli.command_usage()` に一本化し、GUI はそれを import する
（GUI は元から persona_cli を import していたので、依存の向きは変わらない）。

共有化の副産物として、`_print_search` の使い方表示が日本語固定で、英語
ユーザーにも日本語を出していたことが露見した（`lang` を受け取っていなかった）。
"""
from __future__ import annotations

import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

from persona_cli import (  # noqa: E402
    _COMMAND_USAGE, _CONFIRM_PROMPTS, command_usage, confirmation_prompt,
)


class CommandUsageTests(unittest.TestCase):
    def test_every_command_has_both_languages(self):
        for name, entry in _COMMAND_USAGE.items():
            with self.subTest(command=name):
                self.assertTrue(entry.get("ja", "").strip())
                self.assertTrue(entry.get("en", "").strip())

    def test_usage_line_names_its_own_command(self):
        """`/like` の使い方に `/like` が出てくること（コピペ間違いの検出）。"""
        for name, entry in _COMMAND_USAGE.items():
            for lang in ("ja", "en"):
                with self.subTest(command=name, lang=lang):
                    self.assertIn(f"/{name}", entry[lang])

    def test_japanese_heading_is_consistent(self):
        """見出し語が全コマンドで揃っていること（「使い方」と「使用方法」の混在）。"""
        headings = {e["ja"].split(":")[0] for e in _COMMAND_USAGE.values()}
        self.assertEqual(len(headings), 1, f"見出しが割れている: {headings}")

    def test_english_heading_is_consistent(self):
        headings = {e["en"].split(":")[0] for e in _COMMAND_USAGE.values()}
        self.assertEqual(len(headings), 1, f"見出しが割れている: {headings}")

    def test_unknown_command_returns_empty(self):
        self.assertEqual(command_usage("nonexistent"), "")

    def test_unknown_language_falls_back_to_japanese(self):
        self.assertEqual(command_usage("like", "fr"), _COMMAND_USAGE["like"]["ja"])
        self.assertEqual(command_usage("like", "en-GB"), _COMMAND_USAGE["like"]["en"])


class NoInlineUsageStringsTests(unittest.TestCase):
    """使い方の文言をエントリポイント側に直書きしないこと。

    直書きが 1 つでも残ると、そこから再びずれ始める。共有定義を作った意味が
    無くなるので、ソース上で禁止する。
    """

    #: 使い方の一行を示す見出し。これがコマンド名と同じ行にあれば直書き。
    _INLINE = re.compile(r'["\'](?:使い方|使用方法|Usage)\s*[:：][^"\']*?/[a-z-]+')

    def _assert_no_inline_usage(self, filename: str) -> None:
        with open(os.path.join(_MAIN, filename), encoding="utf-8") as fh:
            source = fh.read()
        found = self._INLINE.findall(source)
        self.assertEqual(found, [],
                         f"{filename} に使い方の直書きが残っている: {found}")

    def test_gui_has_no_inline_usage_strings(self):
        self._assert_no_inline_usage("avatar_3d_autonomous_tts.py")

    def test_cli_uses_the_shared_table_only(self):
        """CLI 側は _COMMAND_USAGE の定義行だけが該当し、処理側には無いこと。"""
        with open(os.path.join(_MAIN, "persona_cli.py"), encoding="utf-8") as fh:
            lines = fh.readlines()
        start = next(i for i, l in enumerate(lines) if "_COMMAND_USAGE = {" in l)
        end = next(i for i, l in enumerate(lines[start:], start) if l.startswith("}"))
        outside = "".join(lines[:start] + lines[end + 1:])
        found = self._INLINE.findall(outside)
        self.assertEqual(found, [],
                         f"共有テーブルの外に使い方の直書きがある: {found}")


class ConfirmationPromptTests(unittest.TestCase):
    """破壊的操作の二段階確認が GUI と CLI で同じで、かつ**正しい**指示であること。

    GUI は「もう一度 /clear-log と**言って**ください」/ "Say ... again" だった。
    どちらのインターフェースでもユーザーは打ち込むのだから、これは単なる
    ドリフトではなく誤った指示である。しかも出るのは会話履歴の全消去や
    全データ消去の確認で、言われたとおり「言おう」とした人には、なぜ削除が
    進まないのか分からない。
    """

    def test_every_prompt_has_both_languages(self):
        for name, entry in _CONFIRM_PROMPTS.items():
            for lang in ("ja", "en"):
                with self.subTest(command=name, lang=lang):
                    self.assertTrue(entry.get(lang, "").strip())

    def test_prompt_tells_the_user_to_type_not_to_speak(self):
        """どちらの UI でも入力する操作なので「言う」と案内しないこと。"""
        for name, entry in _CONFIRM_PROMPTS.items():
            with self.subTest(command=name):
                self.assertNotIn("と言って", entry["ja"])
                self.assertNotIn("Say ", entry["en"])
                self.assertIn("入力", entry["ja"])
                self.assertIn("Type ", entry["en"])

    def test_prompt_names_the_command_to_repeat(self):
        """どれを打ち直せばよいかが本文から分かること。"""
        for name, entry in _CONFIRM_PROMPTS.items():
            for lang in ("ja", "en"):
                with self.subTest(command=name, lang=lang):
                    self.assertIn(f"/{name}", entry[lang])

    def test_prompt_states_what_will_be_destroyed(self):
        """何が消えるのかを述べていること（確認の意味が無くならないように）。"""
        markers = {"ja": ("消去", "リセット", "消します"),
                   "en": ("erase", "reset")}
        for name, entry in _CONFIRM_PROMPTS.items():
            for lang in ("ja", "en"):
                with self.subTest(command=name, lang=lang):
                    self.assertTrue(
                        any(m in entry[lang].lower() or m in entry[lang]
                            for m in markers[lang]),
                        f"{name}/{lang} が破壊内容を述べていない: {entry[lang]!r}")

    def test_unknown_command_returns_empty(self):
        self.assertEqual(confirmation_prompt("nonexistent"), "")


class NoInlineConfirmationTests(unittest.TestCase):
    """確認文言もエントリポイント側に直書きしないこと。"""

    # 特定のコマンド名を含む確認文だけを対象にする。コマンド名を含まない
    # 汎用フォールバック（persona_cli を読めない場合の安全網）は共有できない
    # 性質のものなので除く。
    _INLINE = re.compile(
        r'["\'][^"\']*(?:/[a-z-]+\s+again to confirm|もう一度\s*/[a-z-]+)')

    def test_gui_has_no_inline_confirmation(self):
        with open(os.path.join(_MAIN, "avatar_3d_autonomous_tts.py"),
                  encoding="utf-8") as fh:
            found = self._INLINE.findall(fh.read())
        self.assertEqual(found, [], f"GUI に確認文言の直書き: {found}")

    def test_cli_confirmations_live_only_in_the_shared_table(self):
        with open(os.path.join(_MAIN, "persona_cli.py"), encoding="utf-8") as fh:
            lines = fh.readlines()
        start = next(i for i, l in enumerate(lines) if "_CONFIRM_PROMPTS = {" in l)
        end = next(i for i, l in enumerate(lines[start:], start) if l.startswith("}"))
        outside = "".join(lines[:start] + lines[end + 1:])
        # コメント行は説明なので除く
        outside = "\n".join(l for l in outside.split("\n") if not l.lstrip().startswith("#"))
        found = self._INLINE.findall(outside)
        self.assertEqual(found, [], f"共有テーブル外に確認文言: {found}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
