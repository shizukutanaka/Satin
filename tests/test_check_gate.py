"""検証ゲート（リポジトリ root の check.py）自体のテスト。

ゲートを信頼するには、ゲートが「壊れているものを赤にする」ことと
「回しただけで何も壊さない」ことの両方が要る。前者が無ければ緑は無意味だし、
後者が無ければ誰も気軽に回さなくなる。
"""
from __future__ import annotations

import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHECK_PY = os.path.join(_ROOT, "check.py")


def _load_check():
    """check.py をファイルパスから読み込む（root は sys.path に無いため）。"""
    spec = importlib.util.spec_from_file_location("_satin_check", _CHECK_PY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GatePlanTests(unittest.TestCase):
    def setUp(self):
        self.check = _load_check()

    def test_gate_file_exists(self):
        self.assertTrue(os.path.exists(_CHECK_PY))

    def test_static_checks_cover_the_four_pillars(self):
        """型・lint・テスト・設定の 4 つは必ず静的チェックに含まれること。"""
        names = {name for name, _ in self.check._STATIC}
        for required in ("mypy", "ruff", "pytest", "config validate"):
            self.assertIn(required, names)

    def test_fast_mode_skips_smoke_but_keeps_static(self):
        self.assertEqual(self.check.main(["--list", "--fast"]), 0)
        names_fast = {n for n, _ in self.check._STATIC}
        names_full = names_fast | {n for n, _ in self.check._SMOKE}
        self.assertLess(len(names_fast), len(names_full))

    def test_list_mode_does_not_execute_anything(self):
        """--list は計画を出すだけ。実行してしまうと「何が走るか確認する」
        という用途が成立しない。"""
        called = []
        original = self.check._STATIC[:]
        try:
            self.check._STATIC[:] = [
                ("probe", lambda: called.append(1) or self.check.Result("probe", "PASS"))
            ]
            self.check.main(["--list"])
        finally:
            self.check._STATIC[:] = original
        self.assertEqual(called, [])

    def test_mypy_is_invoked_without_a_file_list(self):
        """対象は mypy.ini が決める。ここでファイルを並べると設定と実行が
        ずれ、検査漏れに気づけなくなる。"""
        with open(_CHECK_PY, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn('"-m", "mypy"', source)
        self.assertNotIn('"mypy", "main"', source)


class PersonalDataPreservationTests(unittest.TestCase):
    """ゲートは個人データを一切動かさないこと。

    スモークは本物のプロセスを起動するので、好感度や会話履歴を書き換える。
    「チェックを回しただけ」でユーザーとアバターの親密度が進むのは副作用として
    不当なので、退避と書き戻しを必ず通す。
    """

    def setUp(self):
        self.check = _load_check()
        self.cfg = os.path.join(_ROOT, "config")

    def test_existing_file_is_restored_after_mutation(self):
        target = os.path.join(self.cfg, self.check._PERSONAL_DATA[0])
        if not os.path.exists(target):
            self.skipTest(f"{target} が存在しない環境")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        with self.check._personal_data_preserved():
            with open(target, "w", encoding="utf-8") as fh:
                fh.write('{"affinity": 999.0}')  # スモークによる書き換えを模す
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)

    def test_file_created_during_the_run_is_removed(self):
        """実行前に無かったファイルが残らないこと（新規ユーザーの環境で
        ゲートを回すと好感度ファイルが生えてしまう、という事故を防ぐ）。"""
        names = [n for n in self.check._PERSONAL_DATA
                 if not os.path.exists(os.path.join(self.cfg, n))]
        if not names:
            self.skipTest("全ての個人データファイルが既に存在する環境")
        target = os.path.join(self.cfg, names[0])
        with self.check._personal_data_preserved():
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("{}")
        self.assertFalse(os.path.exists(target), f"{target} が残っている")

    def test_restores_even_when_the_body_raises(self):
        target = os.path.join(self.cfg, self.check._PERSONAL_DATA[0])
        if not os.path.exists(target):
            self.skipTest(f"{target} が存在しない環境")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        with self.assertRaises(RuntimeError):
            with self.check._personal_data_preserved():
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write("clobbered")
                raise RuntimeError("スモークが途中で落ちた場合")
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)

    def test_mood_files_are_listed_as_personal_data(self):
        for name in ("mood.json", "mood_history.jsonl", "user_profile.json"):
            self.assertIn(name, self.check._PERSONAL_DATA)



class PrePushHookTests(unittest.TestCase):
    """The pre-push hook is the gate's automation while CI is not enabled.

    Placing .github/workflows/ci.yml is refused for this repo's agent token on
    both paths — `git push` ("refusing to allow a GitHub App to create or
    update workflow") and the REST contents API (403 "Resource not accessible
    by integration"). Until the owner enables CI, this hook is what makes the
    gate run automatically, so it must keep working and stay discoverable.
    """

    HOOK = os.path.join(_ROOT, ".githooks", "pre-push")

    def test_hook_exists_and_is_executable(self):
        self.assertTrue(os.path.exists(self.HOOK), "pre-push hook is missing")
        if hasattr(os, "access"):
            self.assertTrue(os.access(self.HOOK, os.X_OK),
                            "pre-push hook must be executable or git will ignore it")

    def test_hook_runs_the_same_gate_as_ci(self):
        """One definition of "verified": the hook calls check.py, not its own list."""
        with open(self.HOOK, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("check.py", body)
        for tool in ("pytest", "ruff", "mypy"):
            self.assertNotIn(f"{tool} ", body.replace("check.py", ""),
                             f"the hook must not re-list {tool}; check.py owns the list")

    def test_documented_enable_command_matches_the_directory(self):
        """A wrong path in the docs makes the hook silently never run."""
        for doc in ("README.md", os.path.join("setup", "README.md")):
            path = os.path.join(_ROOT, doc)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if "core.hooksPath" in text:
                self.assertIn("core.hooksPath .githooks", text,
                              f"{doc} points core.hooksPath at the wrong directory")
                return
        self.fail("no document explains how to enable the hook (core.hooksPath)")

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
