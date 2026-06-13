"""
Stdlib-only tests for main/batch_config_utils.py and its thin wrappers
(comment_manager_batch, tts_manager_batch, overlay_manager_batch).

Run: python -m unittest tests.test_batch_config_utils -v
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from batch_config_utils import validate_configs, backup_configs  # noqa: E402


def _write_json(directory, filename, data):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class ValidateConfigsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_empty_list_when_all_valid(self):
        _write_json(self._tmp, "cfg_a.json", {"key1": "v", "key2": "w"})
        errors = validate_configs(
            search_dir=self._tmp,
            glob_pattern="cfg_*.json",
            required_keys=["key1", "key2"],
            desc="test",
            error_summary="errors",
            ok_message="ok",
        )
        self.assertEqual(errors, [])

    def test_returns_errors_for_missing_required_key(self):
        _write_json(self._tmp, "cfg_bad.json", {"key1": "v"})  # missing key2
        errors = validate_configs(
            search_dir=self._tmp,
            glob_pattern="cfg_*.json",
            required_keys=["key1", "key2"],
            desc="test",
            error_summary="errors",
            ok_message="ok",
        )
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("key2" in e for e in errors))

    def test_no_files_returns_empty_list(self):
        errors = validate_configs(
            search_dir=self._tmp,
            glob_pattern="nonexistent_*.json",
            required_keys=["key1"],
            desc="test",
            error_summary="errors",
            ok_message="ok",
        )
        self.assertEqual(errors, [])

    def test_invalid_json_returns_error(self):
        path = os.path.join(self._tmp, "bad.json")
        with open(path, "w") as f:
            f.write("not json {{{")
        errors = validate_configs(
            search_dir=self._tmp,
            glob_pattern="bad.json",
            required_keys=["key"],
            desc="test",
            error_summary="errors",
            ok_message="ok",
        )
        self.assertGreater(len(errors), 0)

    def test_mixed_valid_invalid_counts_errors_only(self):
        _write_json(self._tmp, "cfg_good.json", {"k": 1})
        _write_json(self._tmp, "cfg_bad.json", {})  # missing "k"
        errors = validate_configs(
            search_dir=self._tmp,
            glob_pattern="cfg_*.json",
            required_keys=["k"],
            desc="test",
            error_summary="errors",
            ok_message="ok",
        )
        self.assertEqual(len(errors), 1)


class BackupConfigsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_zip_file(self):
        _write_json(self._tmp, "cfg_x.json", {"a": 1})
        backup_configs(
            search_dir=self._tmp,
            glob_pattern="cfg_*.json",
            zip_prefix="test_backup",
            ok_message_template="Backed up to {zipname}",
            error_prefix="err",
        )
        zips = [f for f in os.listdir(self._tmp) if f.endswith(".zip")]
        self.assertEqual(len(zips), 1)

    def test_zip_contains_config_files(self):
        _write_json(self._tmp, "cfg_y.json", {"b": 2})
        backup_configs(
            search_dir=self._tmp,
            glob_pattern="cfg_*.json",
            zip_prefix="bak",
            ok_message_template="{zipname}",
            error_prefix="err",
        )
        zips = [f for f in os.listdir(self._tmp) if f.endswith(".zip")]
        with zipfile.ZipFile(os.path.join(self._tmp, zips[0])) as zf:
            names = zf.namelist()
        self.assertIn("cfg_y.json", names)

    def test_no_files_creates_empty_zip(self):
        backup_configs(
            search_dir=self._tmp,
            glob_pattern="nonexistent_*.json",
            zip_prefix="empty_bak",
            ok_message_template="{zipname}",
            error_prefix="err",
        )
        zips = [f for f in os.listdir(self._tmp) if f.endswith(".zip")]
        self.assertEqual(len(zips), 1)


class CommentManagerBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_batch_validate_comments_all_valid(self):
        from comment_manager_batch import batch_validate_comments
        _write_json(self._tmp, "comment_manager_a.json",
                    {"comment_source": "youtube", "output_enabled": True})
        result = batch_validate_comments(comment_dir=self._tmp)
        # profile_time wrapper returns None; validate_configs returns list — no crash
        # (function is decorated with @profile_time which returns None)

    def test_batch_validate_comments_missing_key(self):
        from comment_manager_batch import batch_validate_comments
        _write_json(self._tmp, "comment_manager_bad.json", {"comment_source": "yt"})
        # Should not raise
        batch_validate_comments(comment_dir=self._tmp)


class TtsManagerBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_batch_validate_tts_all_valid(self):
        from tts_manager_batch import batch_validate_tts
        _write_json(self._tmp, "tts_default.json",
                    {"voice_type": "female", "enabled": True})
        batch_validate_tts(tts_dir=self._tmp)

    def test_batch_validate_tts_missing_key(self):
        from tts_manager_batch import batch_validate_tts
        _write_json(self._tmp, "tts_bad.json", {"voice_type": "male"})
        batch_validate_tts(tts_dir=self._tmp)


class OverlayManagerBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_batch_validate_overlays_all_valid(self):
        from overlay_manager_batch import batch_validate_overlays
        _write_json(self._tmp, "overlay_main.json",
                    {"overlay_type": "chat", "enabled": True})
        batch_validate_overlays(overlay_dir=self._tmp)

    def test_batch_validate_overlays_missing_key(self):
        from overlay_manager_batch import batch_validate_overlays
        _write_json(self._tmp, "overlay_bad.json", {"overlay_type": "chat"})
        batch_validate_overlays(overlay_dir=self._tmp)


if __name__ == "__main__":
    unittest.main()
