"""
Tests for satin_launcher — the main entry point.

All tests avoid actually launching GUI, Flask, or TTS by mocking out the
underlying _launch_* functions and checking the dispatch logic. Also tests
_check_deps() and _check_config().
"""
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

    def test_no_args_launches_avatar_gui(self):
        """Default mode must launch the real 3D avatar GUI (TTS/mood/log/
        slash commands), not the file-picker-only avatar_loader. Regression
        for a commercial-quality audit finding: the documented launch path
        (this default, launch/win/run_satin.bat, launch/mac/run_satin.sh,
        README) used to dead-end at avatar_loader.AvatarLoaderApp, which
        only remembers a chosen file path and never displays the avatar."""
        with mock.patch.object(satin_launcher, "_launch_avatar_gui") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--no-dep-check"])
            m.assert_called_once()

    def test_no_args_does_not_launch_avatar_loader(self):
        with mock.patch.object(satin_launcher, "_launch_avatar_loader") as loader_m, \
             mock.patch.object(satin_launcher, "_launch_avatar_gui"), \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--no-dep-check"])
            loader_m.assert_not_called()

    def test_avatar_loader_flag_dispatches(self):
        with mock.patch.object(satin_launcher, "_launch_avatar_loader") as m, \
             mock.patch.object(satin_launcher, "_check_deps", return_value=[]), \
             mock.patch.object(satin_launcher, "_check_config"):
            self._run(["--avatar-loader", "--no-dep-check"])
            m.assert_called_once()


class LaunchAvatarGuiTests(unittest.TestCase):
    def _fake_lock(self, acquired=True):
        import single_instance
        fake = mock.Mock()
        fake.acquire.return_value = acquired
        return mock.patch.object(single_instance, "SingleInstance", return_value=fake), fake

    def test_import_failure_prints_error_and_exits(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("PyQt5.QtWidgets", "avatar_3d_autonomous_tts"):
                raise ImportError("simulated: missing GUI dependency")
            return real_import(name, *args, **kwargs)

        patch_lock, fake = self._fake_lock(acquired=True)
        with patch_lock, mock.patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertRaises(SystemExit) as cm:
                satin_launcher._launch_avatar_gui()
            self.assertEqual(cm.exception.code, 1)
        # the lock must be released when the GUI fails to import
        fake.release.assert_called()

    def test_already_running_exits_without_launching(self):
        """When the single-instance lock is held by a live instance, the GUI
        must not launch a second copy — it exits cleanly (code 0)."""
        patch_lock, fake = self._fake_lock(acquired=False)
        with patch_lock, mock.patch.object(satin_launcher, "sys") as _sys:
            _sys.exit.side_effect = SystemExit
            _sys.argv = ["satin_launcher"]
            with self.assertRaises(SystemExit):
                satin_launcher._launch_avatar_gui()
            _sys.exit.assert_any_call(0)

    def test_guard_failure_does_not_block_launch(self):
        """If the guard mechanism itself errors, launch proceeds anyway."""
        import single_instance
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            # GUI deps still missing so we exit(1) after the guard is bypassed;
            # the point is that a guard error doesn't stop us reaching launch.
            if name in ("PyQt5.QtWidgets", "avatar_3d_autonomous_tts"):
                raise ImportError("no GUI")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(single_instance, "SingleInstance",
                               side_effect=RuntimeError("guard boom")), \
             mock.patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertRaises(SystemExit) as cm:
                satin_launcher._launch_avatar_gui()
            self.assertEqual(cm.exception.code, 1)  # reached launch, failed on GUI import


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


class HeadlessModesDoNotNeedTkinterTests(unittest.TestCase):
    """Regression: tkinter used to be unconditionally required
    (dependency_manifest.REQUIRED_PACKAGES), so satin_launcher._check_deps()
    called sys.exit(1) before dispatching to ANY mode on a machine without
    tkinter — including --chat, which --help itself describes as
    "ヘッドレスでアバターと会話する CLI" (a headless CLI). Only
    avatar_loader.py (the default GUI mode) ever imports tkinter, and
    _launch_avatar_loader() already has its own try/except around that
    import with a clear error message. These tests exercise the REAL
    _check_deps() (unlike LaunchDispatchTests above, which mocks it away)
    with tkinter simulated absent, to confirm none of the headless modes
    are blocked by it.
    """

    def _without_tkinter(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tkinter" or name.startswith("tkinter."):
                raise ImportError("simulated: no tkinter in this environment")
            return real_import(name, *args, **kwargs)

        return mock.patch.object(builtins, "__import__", side_effect=fake_import)

    def test_check_deps_does_not_exit_without_tkinter(self):
        with self._without_tkinter():
            result = satin_launcher._check_deps(verbose=False)
        self.assertIsInstance(result, list)

    def test_chat_mode_reaches_launch_chat_without_tkinter(self):
        with self._without_tkinter(), \
             mock.patch.object(satin_launcher, "_launch_chat", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_config"):
            with mock.patch("sys.argv", ["satin_launcher", "--chat"]):
                try:
                    satin_launcher.main()
                except SystemExit:
                    pass
            m.assert_called_once()

    def test_validate_mode_reaches_launch_validate_without_tkinter(self):
        with self._without_tkinter(), \
             mock.patch.object(satin_launcher, "_launch_validate") as m, \
             mock.patch.object(satin_launcher, "_check_config"):
            with mock.patch("sys.argv", ["satin_launcher", "--validate"]):
                try:
                    satin_launcher.main()
                except SystemExit:
                    pass
            m.assert_called_once()

    def test_dashboard_mode_reaches_launch_dashboard_without_tkinter(self):
        with self._without_tkinter(), \
             mock.patch.object(satin_launcher, "_launch_dashboard") as m, \
             mock.patch.object(satin_launcher, "_check_config"):
            with mock.patch("sys.argv", ["satin_launcher", "--dashboard"]):
                try:
                    satin_launcher.main()
                except SystemExit:
                    pass
            m.assert_called_once()

    def test_manage_mode_reaches_launch_manage_without_tkinter(self):
        with self._without_tkinter(), \
             mock.patch.object(satin_launcher, "_launch_manage", side_effect=SystemExit(0)) as m, \
             mock.patch.object(satin_launcher, "_check_config"):
            with mock.patch("sys.argv", ["satin_launcher", "--manage"]):
                try:
                    satin_launcher.main()
                except SystemExit:
                    pass
            m.assert_called_once()


class LogRetentionWiringTests(unittest.TestCase):
    """The conversation-log retention window is applied once, at startup.

    Every entry point goes through main(), so this is the single call site —
    the GUI, --chat and --dashboard all inherit it. --validate is exempt: it
    exists to inspect configuration, and must not delete data as a side effect.
    """

    def _run(self, argv):
        with mock.patch.object(satin_launcher, "_check_deps"), \
             mock.patch.object(satin_launcher, "_check_config"), \
             mock.patch.object(satin_launcher, "_apply_log_retention") as m, \
             mock.patch.object(satin_launcher, "_launch_avatar_gui"), \
             mock.patch.object(satin_launcher, "_launch_chat"), \
             mock.patch.object(satin_launcher, "_launch_validate"):
            with mock.patch("sys.argv", argv):
                try:
                    satin_launcher.main()
                except SystemExit:
                    pass
            return m

    def test_applied_on_default_gui_launch(self):
        self._run(["satin_launcher"]).assert_called_once()

    def test_applied_on_chat_launch(self):
        self._run(["satin_launcher", "--chat"]).assert_called_once()

    def test_not_applied_on_validate(self):
        self._run(["satin_launcher", "--validate"]).assert_not_called()

    def test_helper_is_silent_when_nothing_was_pruned(self):
        import io
        import contextlib
        buf = io.StringIO()
        with mock.patch("log_retention.apply_retention_if_configured",
                        return_value={"pruned": False, "days": 0, "removed": 0,
                                      "archives_removed": 0, "kept": 0}):
            with contextlib.redirect_stdout(buf):
                satin_launcher._apply_log_retention()
        self.assertEqual(buf.getvalue(), "")

    def test_helper_reports_what_it_removed(self):
        import io
        import contextlib
        buf = io.StringIO()
        with mock.patch("log_retention.apply_retention_if_configured",
                        return_value={"pruned": True, "days": 90, "removed": 12,
                                      "archives_removed": 2, "kept": 5}):
            with contextlib.redirect_stdout(buf):
                satin_launcher._apply_log_retention()
        out = buf.getvalue()
        self.assertIn("90", out)
        self.assertIn("12", out)

    def test_helper_never_blocks_startup(self):
        with mock.patch("log_retention.apply_retention_if_configured",
                        side_effect=RuntimeError("boom")):
            satin_launcher._apply_log_retention()  # must not raise


if __name__ == "__main__":
    unittest.main()
