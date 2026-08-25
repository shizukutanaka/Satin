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

from persona_cli import _COMMAND_USAGE, command_usage  # noqa: E402


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
