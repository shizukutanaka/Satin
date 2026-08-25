"""同じコマンドを GUI と CLI に打ち、応答が食い違わないことを検証する。

## なぜこのテストがあるか

このリポジトリでは、同じコマンドが 2 箇所に独立して実装されている（GUI の
`_cmd_*_gui` と CLI の分岐）。手作業で両方に打って並べる、という比較を実際に
行ったところ、**その 1 回で 3 件の欠陥が出た**:

- `/forget-me`: GUI だけ二段階確認が無く、打ち間違い 1 回で呼び名・誕生日・
  趣味・覚えた事実が復元不能に消えた。
- `/forget-all`: CLI に実装が無く、打っても会話として流れて何も消えなかった。
  privacy の中核機能が沈黙で失敗していた。
- 使い方・確認文言が 11 箇所でずれていた（「使い方」対「使用方法」など）。

人が思い出したときにだけ行う比較では、次のずれは次に誰かが気づくまで残る。
毎回の実行で比較する。

## 何を比較し、何を比較しないか

比較するのは**同じ入力に対する応答テキスト**である。ただし正当な差がある:

- CLI はアバター名を前置する（`Mimi: ...`）。UI の表示規約なので剥がす。
- 片方にしか存在しないコマンドがある（`/avatar` は 3D 専用、`/quit` と
  `/name` は CLI 専用）。明示的に除外する。
- 依存が無い状態での「(利用できません)」系は、GUI と CLI で文面が異なりうる
  （GUI はアバターが喋る、CLI は状態表示）。ここでは**確認・使い方・未知
  コマンド**という、文言が一致すべきと決めた種類だけを対象にする。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conftest import make_qt_stub  # noqa: E402
import avatar_3d_autonomous_tts as gui  # noqa: E402
import persona_cli  # noqa: E402
from persona import Persona  # noqa: E402

_PERSONA = Persona.from_dict({
    "name": "Mimi",
    "default_lang": "ja",
    "responses": {"ja": {"rules": [], "fallback": ["FB"]}},
}, lang="ja")


class _Driver:
    def __init__(self, inputs):
        self._inputs = list(inputs)
        self.out = []

    def input_fn(self, prompt=""):
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def output_fn(self, line):
        self.out.append(line)


def _fake_tracker():
    """確認経路まで到達させるための最小の好感度トラッカー。"""
    tracker = mock.Mock()
    tracker.affinity = 50.0
    tracker.level = "neutral"
    tracker.interactions = 0
    tracker.label.return_value = "ふつう"
    return tracker


def _gui_replies(commands, with_mood=False):
    """GUI に順に打ち込み、各コマンドの応答を返す。"""
    viewer = make_qt_stub(gui.AutonomousAvatarViewer)
    viewer.comment_text = ""
    viewer.talk_text = ""
    viewer.mode = "idle"
    viewer.ticks = 0
    viewer.tts_queue = None
    viewer.pending_fact_key = None
    for attr in gui._PENDING_CONFIRMATIONS:
        setattr(viewer, attr, False)
    out = []
    mood_patch = (mock.patch.object(gui, "get_mood_tracker", _fake_tracker)
                  if with_mood else mock.patch.object(gui, "get_mood_tracker", None))
    with mock.patch.object(gui, "get_conversation_log", None), mood_patch, \
         mock.patch.object(gui, "_get_user_profile_gui", None), \
         mock.patch.object(gui.AutonomousBehaviorMixin, "persona",
                           property(lambda s: _PERSONA)):
        for command in commands:
            viewer.comment_text = ""
            viewer.speak_comment(command)
            out.append(viewer.comment_text)
    return out


def _cli_replies(commands, mood=None):
    """CLI に順に打ち込み、各コマンドの応答を返す（アバター名の前置は剥がす）。

    言語は persona.lang で決まる（run_chat は lang 引数を取らない）。
    """
    driver = _Driver(list(commands))
    persona_cli.run_chat(
        persona=_PERSONA, conv_log=None, mood=mood, profile=None,
        input_fn=driver.input_fn, output_fn=driver.output_fn, greet=False,
    )
    prefix = f"{_PERSONA.name}: "
    return [line[len(prefix):] if line.startswith(prefix) else line
            for line in driver.out if line.strip()]


class UnknownCommandParityTests(unittest.TestCase):
    def test_same_reply_for_an_unrecognised_command(self):
        expected = persona_cli.unknown_command_reply("nope", "ja")
        self.assertIn(expected, _gui_replies(["/nonexistent"])[0])
        self.assertTrue(any(expected in line for line in _cli_replies(["/nonexistent"])))

    def test_same_reply_for_a_typo_of_a_real_command(self):
        expected = persona_cli.unknown_command_reply("mod", "ja")
        self.assertIn(expected, _gui_replies(["/mod"])[0])
        self.assertTrue(any(expected in line for line in _cli_replies(["/mod"])))


class UsageLineParityTests(unittest.TestCase):
    """引数が要るコマンドを引数なしで打ったとき、同じ使い方が出ること。"""

    COMMANDS = ("/like", "/forget", "/forget-fact", "/callme", "/birthday")

    def test_usage_lines_match(self):
        gui_out = _gui_replies(list(self.COMMANDS))
        cli_out = _cli_replies(list(self.COMMANDS))
        for command, from_gui in zip(self.COMMANDS, gui_out):
            expected = persona_cli.command_usage(command.lstrip("/"), "ja")
            with self.subTest(command=command):
                self.assertEqual(from_gui, expected)
                self.assertTrue(any(expected in line for line in cli_out),
                                f"CLI に {command} の使い方が出ていない")


class DestructiveConfirmationParityTests(unittest.TestCase):
    """破壊的コマンドが、両方で同じ確認文を出し、1 回では実行しないこと。"""

    COMMANDS = ("/forget-me", "/forget-all", "/reset-mood", "/clear-log")

    def test_first_press_asks_the_same_question(self):
        gui_out = _gui_replies(list(self.COMMANDS), with_mood=True)
        cli_out = _cli_replies(list(self.COMMANDS), mood=_fake_tracker())
        for command, from_gui in zip(self.COMMANDS, gui_out):
            expected = persona_cli.confirmation_prompt(command.lstrip("/"), "ja")
            with self.subTest(command=command):
                self.assertEqual(from_gui, expected)
                self.assertTrue(any(expected in line for line in cli_out),
                                f"CLI が {command} の確認を出していない")

    def test_no_destructive_command_acts_on_a_single_press(self):
        """1 回打っただけで実行に進まないこと（両インターフェース）。"""
        for command in self.COMMANDS:
            expected = persona_cli.confirmation_prompt(command.lstrip("/"), "ja")
            with self.subTest(command=command):
                self.assertEqual(_gui_replies([command], with_mood=True)[0], expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
