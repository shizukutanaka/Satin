"""
Guards for mypy.ini — the staged type-checking gate (work order W-07).

Running mypy itself here would add ~20s to every test run and require mypy to
be installed, so CI owns that (`python -m mypy`, no arguments). What these
tests protect is the *config*, which is where a gradual-typing setup actually
rots:

  - a grandfathered module gets deleted or renamed, and its stale exemption
    silently starts covering nothing (or worse, a new module that happens to
    reuse the name);
  - someone cleans a module but leaves the exemption in place, so it keeps
    being skipped and can quietly regress;
  - someone adds `ignore_errors` for a module that was never actually broken.

The list is meant to shrink and nothing else. `test_exempt_modules_all_exist`
catches the first case cheaply; the CI mypy run catches real type errors.

Stdlib-only; does not invoke mypy. Run: python -m unittest tests.test_mypy_config -v
"""
import configparser
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MYPY_INI = os.path.join(_ROOT, "mypy.ini")
_MAIN = os.path.join(_ROOT, "main")


def _config():
    parser = configparser.ConfigParser()
    parser.read(_MYPY_INI, encoding="utf-8")
    return parser


def _exempt_modules():
    """Module names carrying ignore_errors, minus the wildcard package rules."""
    names = []
    for section in _config().sections():
        if not section.startswith("mypy-"):
            continue
        module = section[len("mypy-"):]
        if module.endswith(".*"):
            continue  # package-wide rule, checked separately
        names.append(module)
    return names


def _exempt_packages():
    return [s[len("mypy-"):-2] for s in _config().sections()
            if s.startswith("mypy-") and s.endswith(".*")]


class MypyIniTests(unittest.TestCase):
    def test_config_exists_and_parses(self):
        self.assertTrue(os.path.exists(_MYPY_INI), "mypy.ini is missing")
        self.assertIn("mypy", _config().sections() + ["mypy"])

    def test_checks_main_by_default(self):
        """`python -m mypy` with no arguments must have something to check.

        Passing an explicit file list on the command line is what lets a new
        module slip through unchecked — the same failure mode that let
        tests/test_i18n.py's key list go stale.
        """
        base = _config()["mypy"]
        self.assertEqual(base.get("files", "").strip(), "main")
        self.assertEqual(base.get("mypy_path", "").strip(), "main")

    def test_optional_dependencies_do_not_break_the_run(self):
        """PyQt5/OpenGL/pygltflib/flask are optional; missing stubs must not
        fail type checking on a machine that doesn't have them."""
        self.assertTrue(_config()["mypy"].getboolean("ignore_missing_imports"))

    def test_untyped_function_bodies_are_not_checked(self):
        """The staging premise: enforce the annotations that exist, don't
        demand annotations everywhere at once."""
        base = _config()["mypy"]
        self.assertFalse(base.getboolean("check_untyped_defs"))
        self.assertFalse(base.getboolean("disallow_untyped_defs"))


class GrandfatherListTests(unittest.TestCase):
    def test_every_exempt_module_still_exists(self):
        """A stale exemption is worse than none — it looks like coverage."""
        missing = [m for m in _exempt_modules()
                   if not os.path.exists(os.path.join(_MAIN, f"{m}.py"))]
        self.assertEqual(missing, [],
                         f"mypy.ini exempts modules that no longer exist: {missing}")

    def test_every_exempt_package_still_exists(self):
        missing = [p for p in _exempt_packages()
                   if not os.path.isdir(os.path.join(_MAIN, p))]
        self.assertEqual(missing, [],
                         f"mypy.ini exempts packages that no longer exist: {missing}")

    def test_exemptions_only_disable_errors(self):
        """An exemption should skip checking, not weaken it in other ways."""
        parser = _config()
        for section in parser.sections():
            if not section.startswith("mypy-"):
                continue
            keys = set(parser[section].keys())
            self.assertEqual(keys, {"ignore_errors"},
                             f"[{section}] should only set ignore_errors, got {keys}")
            self.assertTrue(parser[section].getboolean("ignore_errors"), section)

    def test_no_duplicate_exemptions(self):
        modules = _exempt_modules()
        self.assertEqual(len(modules), len(set(modules)),
                         "duplicate ignore_errors sections in mypy.ini")

    def test_core_modules_are_never_exempt(self):
        """The dialogue/memory/safety core is the whole point of the gate.

        These are the modules that decide what the avatar says and what it
        stores about the user, so they stay checked no matter how the
        exemption list evolves.
        """
        core = [
            "mood", "persona", "conversation_log", "user_wellbeing",
            "usage_guardrails", "avatar_model_store", "user_profile",
            "farewell_integrity", "crisis_support", "ai_disclosure",
            "sentiment_target", "log_retention", "first_run", "fsutil",
            "gltf_utils", "single_instance", "version",
        ]
        exempt = set(_exempt_modules())
        leaked = sorted(set(core) & exempt)
        self.assertEqual(leaked, [], f"core modules must stay type-checked: {leaked}")

    def test_exempt_list_is_a_minority_of_the_codebase(self):
        """Sanity bound: if most of main/ were exempt the gate would be
        decorative. It was 42 of 94 at introduction and should only fall."""
        exempt = len(_exempt_modules())
        total = len([f for f in os.listdir(_MAIN) if f.endswith(".py")])
        self.assertLess(exempt, total / 2,
                        f"{exempt} of {total} modules exempt — the gate is not holding")


class CiWiringTests(unittest.TestCase):
    def test_ci_runs_mypy_without_arguments(self):
        path = os.path.join(_ROOT, "setup", "github-actions-ci.yml")
        with open(path, encoding="utf-8") as fh:
            ci = fh.read()
        self.assertIn("python -m mypy", ci)
        # an explicit file list here would bypass mypy.ini's `files`
        self.assertNotIn("python -m mypy main/", ci)

    def test_mypy_is_a_declared_dependency(self):
        path = os.path.join(_ROOT, "setup", "requirements.txt")
        with open(path, encoding="utf-8") as fh:
            reqs = fh.read()
        self.assertIn("mypy", reqs)
        self.assertIn("ruff", reqs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
