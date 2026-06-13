"""
Tests for satin_launcher — the main entry point.

All tests avoid actually launching GUI, Flask, or TTS by mocking out the
underlying _launch_* functions and checking the dispatch logic. Also tests
_check_deps() and _check_config().
"""
import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock

# satin_launcher is at the repo root, not in main/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import satin_launcher  # noqa: E402


class CheckDepsTests(unittest.TestCase):
    def _with_no_required(self):
        """Context: empty _REQUIRED_DEPS so tkinter absence doesn't exit."""
        return mock.patch.object(satin_launcher, "_REQUIRED_DEPS", [])

    def test_returns_list(self):
        with self._with_no_required():
            result = satin_launcher._check_deps(verbose=False)
        self.assertIsInstance(result, list)

    def test_missing_optional_are_listed(self):
        """Packages that are genuinely missing appear in the returned list."""
        with self._with_no_required():
            result = satin_launcher._check_deps(verbose=False)
        self.assertIsInstance(result, list)

    def test_verbose_prints_missing(self):
        """verbose=True prints missing packages (if any)."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with self._with_no_required(), redirect_stdout(buf):
            satin_launcher._check_deps(verbose=True)
        # Should not raise regardless of what's installed

    def test_required_dep_missing_exits(self):
        """If a required dep is missing, _check_deps calls sys.exit."""
        with mock.patch.object(satin_launcher, "_REQUIRED_DEPS",
                               [("_nonexistent_pkg_xyz_", "install hint")]):
            with self.assertRaises(SystemExit):
                satin_launcher._check_deps(verbose=False)


class CheckConfigTests(unittest.TestCase):
    def test_no_crash_with_existing_config_dir(self):
        satin_launcher._check_config()  # repo has config/ — should not raise

    def test_no_crash_with_missing_config_dir(self):
        with mock.patch.object(satin_launcher, "_ROOT", "/nonexistent/path"):
            satin_launcher._check_config()  # should warn but not raise


class LaunchDispatchTests(unittest.TestCase):
    """Test that main() dispatches to the right _launch_* function."""

    def _run(self, argv):
        with mock.patch("sys.argv", ["satin_launcher"] + argv):
            try:
                satin_launcher.main()
            except SystemExit:
                pass

    def test_validate_dispatches(self):
        with mock.patch.object(satin_launcher, "_launch_validate") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--validate", "--no-dep-check"])
            m.assert_called_once()

    def test_chat_dispatches(self):
        with mock.patch.object(satin_launcher, "_launch_chat", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--chat", "--no-dep-check"])
            m.assert_called_once()

    def test_chat_lang_forwarded(self):
        with mock.patch.object(satin_launcher, "_launch_chat", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--chat", "--lang", "en", "--no-dep-check"])
            m.assert_called_once_with(lang="en", no_greet=False, no_mood=False)

    def test_chat_no_greet_forwarded(self):
        with mock.patch.object(satin_launcher, "_launch_chat", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--chat", "--no-greet", "--no-dep-check"])
            m.assert_called_once_with(lang=None, no_greet=True, no_mood=False)

    def test_manage_dispatches(self):
        with mock.patch.object(satin_launcher, "_launch_manage", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--manage", "--no-dep-check"])
            m.assert_called_once()

    def test_dashboard_dispatches(self):
        with mock.patch.object(satin_launcher, "_launch_dashboard") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--dashboard", "--no-dep-check"])
            m.assert_called_once()

    def test_dashboard_host_port_forwarded(self):
        with mock.patch.object(satin_launcher, "_launch_dashboard") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--dashboard", "--host", "0.0.0.0", "--port", "8080", "--no-dep-check"])
            m.assert_called_once_with(host="0.0.0.0", port=8080)

    def test_no_args_tries_gui_loader(self):
        with mock.patch.object(satin_launcher, "_launch_avatar_loader") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--no-dep-check"])
            m.assert_called_once()


class LaunchValidateTests(unittest.TestCase):
    def test_validate_ok_does_not_exit(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "good.json"), "w") as f:
                f.write("{}")
            with mock.patch.object(satin_launcher, "_ROOT", d):
                satin_launcher._launch_validate()  # must not raise

    def test_validate_bad_raises_systemexit(self):
        with tempfile.TemporaryDirectory() as d:
            # _launch_validate() looks in {_ROOT}/config/*.json
            config_dir = os.path.join(d, "config")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, "bad.json"), "w") as f:
                f.write("invalid json !!!")
            with mock.patch.object(satin_launcher, "_ROOT", d):
                with self.assertRaises(SystemExit) as cm:
                    satin_launcher._launch_validate()
                self.assertEqual(cm.exception.code, 1)


class LaunchChatTests(unittest.TestCase):
    def test_launch_chat_calls_persona_cli_main(self):
        import builtins
        orig_input = builtins.input
        builtins.input = lambda *a, **k: (_ for _ in ()).throw(EOFError())
        try:
            with self.assertRaises(SystemExit) as cm:
                satin_launcher._launch_chat(lang="en", no_greet=True, no_mood=True)
            self.assertEqual(cm.exception.code, 0)
        finally:
            builtins.input = orig_input


class LaunchManageTests(unittest.TestCase):
    def test_launch_manage_no_args_exits_0(self):
        with self.assertRaises(SystemExit) as cm:
            satin_launcher._launch_manage([])
        self.assertEqual(cm.exception.code, 0)

    def test_launch_manage_validate_exits_0_with_valid_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.json"), "w") as f:
                f.write("{}")
            with self.assertRaises(SystemExit) as cm:
                satin_launcher._launch_manage(["validate", "--config-dir", d])
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
