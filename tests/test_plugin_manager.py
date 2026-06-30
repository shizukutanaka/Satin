"""
Regression tests for plugin_manager.py.

Key bug fixed: _load_plugin() referenced PluginBase without importing it,
causing NameError: name 'PluginBase' is not defined on every plugin load.

Run: python -m unittest tests.test_plugin_manager -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from plugin_manager import PluginManager  # noqa: E402
from plugin_base import PluginBase  # noqa: E402


class _StubLogger:
    """Minimal logger stub matching the interface PluginManager expects."""
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class PluginManagerImportTests(unittest.TestCase):
    def test_plugin_base_importable_in_plugin_manager(self):
        """PluginBase must be reachable from plugin_manager (was NameError before fix)."""
        import plugin_manager as pm
        self.assertTrue(hasattr(pm, 'PluginBase'))

    def test_load_plugin_nonexistent_file_raises_plugin_error(self):
        """_load_plugin on a nonexistent file raises PluginError, not NameError."""
        from error_handling import PluginError
        from pathlib import Path
        pm = PluginManager(_StubLogger())
        with self.assertRaises(PluginError):
            pm._load_plugin(Path("/nonexistent/my_plugin.py"))

    def test_load_plugins_no_nameerror_on_missing_dir(self):
        """load_plugins on a missing plugin dir raises PluginError, not NameError."""
        from error_handling import PluginError
        pm = PluginManager(_StubLogger())
        pm.plugin_directory = type('P', (), {'exists': lambda s: False,
                                             '__fspath__': lambda s: 'plugins'})()
        with self.assertRaises(PluginError):
            pm.load_plugins()

    def test_get_plugin_raises_for_unknown(self):
        from error_handling import PluginError
        pm = PluginManager(_StubLogger())
        with self.assertRaises(PluginError):
            pm.get_plugin("nonexistent")

    def test_plugin_base_is_abstract(self):
        """PluginBase cannot be instantiated directly (it has abstract methods)."""
        with self.assertRaises(TypeError):
            PluginBase()

    def test_load_valid_plugin_file(self):
        """Loading a valid plugin file instantiates the concrete subclass."""
        from pathlib import Path

        # Write a plugin that imports PluginBase from the same sys.path as plugin_manager
        plugin_src = f"""\
import sys
sys.path.insert(0, {_MAIN!r})
from plugin_base import PluginBase

class MyPlugin(PluginBase):
    def configure(self, config): self.config = config
    def start(self): pass
    def stop(self): pass
    def process(self, data): return data
"""
        with tempfile.TemporaryDirectory() as d:
            plugin_path = os.path.join(d, "my_plugin.py")
            with open(plugin_path, "w") as f:
                f.write(plugin_src)

            pm = PluginManager(_StubLogger())
            pm.plugin_directory = Path(d)
            pm._load_plugin_config = lambda: None
            pm.plugin_config = {}

            pm._load_plugin(Path(plugin_path))
            self.assertIn("my_plugin", pm.plugins)


class NullSpecLoaderTests(unittest.TestCase):
    """Regression: spec.loader can be None after spec_from_file_location().
    Without an explicit check, spec.loader.exec_module() raises AttributeError
    with a confusing traceback.  The fix adds `if spec.loader is None: raise ImportError`.
    """

    def test_null_loader_raises_plugin_error(self):
        import unittest.mock as mock
        from pathlib import Path
        from error_handling import PluginError

        pm = PluginManager(_StubLogger())
        pm.plugin_directory = Path("/fake")
        pm.plugin_config = {}

        fake_spec = mock.MagicMock()
        fake_spec.loader = None  # triggers the new guard

        with mock.patch('plugin_manager.importlib.util.spec_from_file_location',
                        return_value=fake_spec):
            with self.assertRaises(PluginError):
                pm._load_plugin(Path("/fake/my_plugin.py"))


class ImportlibUtilImportTests(unittest.TestCase):
    """plugin_manager uses importlib.util.spec_from_file_location, but
    `import importlib` alone does NOT expose importlib.util — it must be
    imported explicitly.  In-process tests miss this because pytest and other
    modules import importlib.util first; a clean subprocess catches it.
    """

    def test_plugin_manager_imports_importlib_util(self):
        import subprocess
        code = (
            "import importlib\n"
            "import sys\n"
            f"sys.path.insert(0, {_MAIN!r})\n"
            # Importing the module must make importlib.util accessible; if the
            # module forgot `import importlib.util`, this raises AttributeError.
            "import plugin_manager\n"
            "importlib.util.spec_from_file_location\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         f"clean-interpreter import failed:\n{result.stderr}")
        self.assertIn("OK", result.stdout)

    def test_config_plugins_imports_importlib_util(self):
        import subprocess
        _CONFIG = os.path.join(_MAIN, "config")
        code = (
            "import importlib\n"
            "import sys\n"
            f"sys.path.insert(0, {_MAIN!r})\n"
            f"sys.path.insert(0, {_CONFIG!r})\n"
            "import plugins\n"  # main/config/plugins.py
            "importlib.util.spec_from_file_location\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         f"clean-interpreter import failed:\n{result.stderr}")
        self.assertIn("OK", result.stdout)


class PluginBaseValidationTests(unittest.TestCase):
    def test_validate_config_passes_with_required_keys(self):
        class ConcretePlugin(PluginBase):
            def configure(self, cfg): pass
            def start(self): pass
            def stop(self): pass
            def process(self, data): return data

        p = ConcretePlugin()
        p.validate_config({"a": 1, "b": 2}, ["a", "b"])  # must not raise

    def test_validate_config_raises_on_missing_key(self):
        from error_handling import PluginError

        class ConcretePlugin(PluginBase):
            def configure(self, cfg): pass
            def start(self): pass
            def stop(self): pass
            def process(self, data): return data

        p = ConcretePlugin()
        with self.assertRaises(PluginError):
            p.validate_config({"a": 1}, ["a", "missing_key"])


class LoadPluginsIsolationTests(unittest.TestCase):
    """Regression: load_plugins() propagated a single plugin's PluginError
    and aborted the batch, leaving successfully-loaded earlier plugins
    inaccessible and never loading plugins that came later in the glob."""

    def _plugin_src(self, class_name):
        return f"""\
import sys
sys.path.insert(0, {_MAIN!r})
from plugin_base import PluginBase

class {class_name}(PluginBase):
    def configure(self, config): self.config = config
    def start(self): pass
    def stop(self): pass
    def process(self, data): return data
"""

    def test_bad_plugin_does_not_prevent_good_plugins_loading(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            # Write a valid plugin
            with open(os.path.join(d, "good_plugin.py"), "w") as f:
                f.write(self._plugin_src("GoodPlugin"))

            # Write a plugin that raises on import
            with open(os.path.join(d, "bad_plugin.py"), "w") as f:
                f.write("raise RuntimeError('intentional import failure')\n")

            warnings = []

            class CapturingLogger(_StubLogger):
                def warning(self, msg):
                    warnings.append(msg)

            pm = PluginManager(CapturingLogger())
            pm.plugin_directory = Path(d)
            pm._load_plugin_config = lambda: None
            pm.plugin_config = {}

            # Must not raise — the bad plugin is skipped, the good one loads.
            pm.load_plugins()

            self.assertIn("good_plugin", pm.plugins)
            self.assertNotIn("bad_plugin", pm.plugins)
            # A warning about the failure must be emitted.
            self.assertTrue(any("bad_plugin" in w for w in warnings))


class ReloadPluginStopTests(unittest.TestCase):
    """Regression: reload_plugin() replaced the old plugin instance without
    calling stop(), leaking any threads or file handles the plugin held."""

    def _plugin_src(self, class_name, extra_body=""):
        return f"""\
import sys
sys.path.insert(0, {_MAIN!r})
from plugin_base import PluginBase

class {class_name}(PluginBase):
    def configure(self, config): self.config = config
    def start(self): pass
    def stop(self): pass
    def process(self, data): return data
{extra_body}
"""

    def test_stop_called_on_old_plugin_before_reload(self):
        from pathlib import Path

        stop_calls = []

        with tempfile.TemporaryDirectory() as d:
            plugin_path = os.path.join(d, "my_plugin.py")
            with open(plugin_path, "w") as f:
                f.write(self._plugin_src("MyPlugin"))

            pm = PluginManager(_StubLogger())
            pm.plugin_directory = Path(d)
            pm._load_plugin_config = lambda: None
            pm.plugin_config = {}
            pm._load_plugin(Path(plugin_path))

            # Monkey-patch stop() on the live instance to record the call.
            pm.plugins["my_plugin"].stop = lambda: stop_calls.append(True)

            pm.reload_plugin("my_plugin")

        self.assertEqual(len(stop_calls), 1, "stop() must be called on the old plugin")

    def test_stop_exception_does_not_abort_reload(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            plugin_path = os.path.join(d, "crashing_plugin.py")
            with open(plugin_path, "w") as f:
                f.write(self._plugin_src("CrashingPlugin"))

            warnings = []

            class CapturingLogger(_StubLogger):
                def warning(self, msg):
                    warnings.append(msg)

            pm = PluginManager(CapturingLogger())
            pm.plugin_directory = Path(d)
            pm._load_plugin_config = lambda: None
            pm.plugin_config = {}
            pm._load_plugin(Path(plugin_path))

            # Make stop() raise
            pm.plugins["crashing_plugin"].stop = lambda: (_ for _ in ()).throw(
                RuntimeError("cleanup failed")
            )

            # Must not raise — the warning is logged, reload proceeds.
            pm.reload_plugin("crashing_plugin")
            self.assertIn("crashing_plugin", pm.plugins)
            self.assertTrue(any("stop()" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
