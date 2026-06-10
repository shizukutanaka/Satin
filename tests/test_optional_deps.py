"""
Stdlib-only regression tests confirming optional-dependency modules import
cleanly when deps (pydantic, tqdm, sounddevice, PyQt5, etc.) are absent.

Run: python -m unittest tests.test_optional_deps -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class SchemaValidatorsTests(unittest.TestCase):
    def test_imports_without_pydantic(self):
        # Previously: ModuleNotFoundError: No module named 'pydantic'
        import schema_validators
        self.assertTrue(hasattr(schema_validators, "ContentType"))

    def test_pydantic_flag_set(self):
        import schema_validators
        self.assertIsInstance(schema_validators._PYDANTIC_AVAILABLE, bool)


class UtilsBatchTests(unittest.TestCase):
    def test_imports_without_tqdm(self):
        # Previously: ModuleNotFoundError: No module named 'tqdm'
        import utils_batch
        self.assertTrue(callable(utils_batch.batch_process))

    def test_batch_process_runs_without_tqdm(self):
        import utils_batch
        results = utils_batch.batch_process(lambda x: x * 2, [1, 2, 3])
        self.assertEqual(sorted(results), [2, 4, 6])

    def test_batch_process_tolerates_partial_failure(self):
        import utils_batch

        def boom_on_zero(x):
            if x == 0:
                raise ValueError("zero!")
            return x * 10

        results = utils_batch.batch_process(boom_on_zero, [-1, 0, 1, 2])
        # One failure: that slot becomes None, others succeed.
        self.assertIn(None, results)
        non_null = [r for r in results if r is not None]
        self.assertEqual(sorted(non_null), [-10, 10, 20])


class TtsVirtualAudioTests(unittest.TestCase):
    def test_imports_without_audio_gui_deps(self):
        # Previously: ModuleNotFoundError: No module named 'sounddevice'
        import tts_with_virtual_audio as tva
        self.assertIsNotNone(tva)

    def test_audio_devices_is_list_when_sounddevice_absent(self):
        import tts_with_virtual_audio as tva
        # When sounddevice is None, AUDIO_DEVICES should be an empty list
        if tva.sd is None:
            self.assertIsInstance(tva.AUDIO_DEVICES, list)
            self.assertIsInstance(tva.OUTPUT_DEVICES, list)

    def test_main_window_class_defined(self):
        import tts_with_virtual_audio as tva
        # class MainWindow(QMainWindow if ... else object) — must be a class
        self.assertTrue(isinstance(tva.MainWindow, type))


class BatchTestUtilTests(unittest.TestCase):
    def test_imports_after_utils_batch_fixed(self):
        # batch_test_util imports utils_batch which previously crashed on tqdm
        import batch_test_util
        self.assertTrue(hasattr(batch_test_util, "generate_dummy_configs"))


if __name__ == "__main__":
    unittest.main()
