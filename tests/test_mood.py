"""
Unit tests for mood.MoodTracker — the affinity / relationship system.

Covers: positive/negative sentiment scoring, clamping, per-message cap,
levels & labels, JSON persistence (save/load roundtrip, missing/corrupt files),
config-driven keyword overrides, and the singleton.
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import mood as _mood  # noqa: E402
from mood import (  # noqa: E402
    AFFINITY_MAX,
    AFFINITY_MIN,
    AFFINITY_START,
    MoodTracker,
    affinity_label,
    affinity_level,
    get_mood_tracker,
    reset_mood_tracker,
)


class ScoringTests(unittest.TestCase):
    def test_starts_at_default(self):
        self.assertEqual(MoodTracker().affinity, AFFINITY_START)

    def test_positive_increases(self):
        m = MoodTracker()
        delta = m.register("ありがとう、大好き！")
        self.assertGreater(delta, 0)
        self.assertGreater(m.affinity, AFFINITY_START)

    def test_negative_decreases(self):
        m = MoodTracker()
        delta = m.register("きらい、うざい")
        self.assertLess(delta, 0)
        self.assertLess(m.affinity, AFFINITY_START)

    def test_english_keywords(self):
        m = MoodTracker()
        m.register("thank you, I love you")
        self.assertGreater(m.affinity, AFFINITY_START)

    def test_neutral_text_no_change(self):
        m = MoodTracker()
        delta = m.register("今日は水曜日です")
        self.assertEqual(delta, 0.0)
        self.assertEqual(m.affinity, AFFINITY_START)

    def test_empty_text_no_change(self):
        m = MoodTracker()
        self.assertEqual(m.register(""), 0.0)
        self.assertEqual(m.register("   "), 0.0)

    def test_interactions_counter(self):
        m = MoodTracker()
        m.register("hello")
        m.register("thanks")
        self.assertEqual(m.interactions, 2)

    def test_empty_text_does_not_count_interaction(self):
        m = MoodTracker()
        m.register("")
        self.assertEqual(m.interactions, 0)


class ClampTests(unittest.TestCase):
    def test_cannot_exceed_max(self):
        m = MoodTracker(affinity=99)
        for _ in range(20):
            m.register("ありがとう大好きかわいいうれしい")
        self.assertLessEqual(m.affinity, AFFINITY_MAX)

    def test_cannot_go_below_min(self):
        m = MoodTracker(affinity=2)
        for _ in range(20):
            m.register("きらいうざい最悪ばか")
        self.assertGreaterEqual(m.affinity, AFFINITY_MIN)

    def test_per_message_cap(self):
        # Many positive words in one message must not move more than the cap (10).
        m = MoodTracker(affinity=50)
        m.register("ありがとう 感謝 好き 大好き かわいい うれしい すごい やさしい")
        self.assertLessEqual(m.affinity - 50, 10.0)

    def test_init_clamps_out_of_range(self):
        self.assertEqual(MoodTracker(affinity=999).affinity, AFFINITY_MAX)
        self.assertEqual(MoodTracker(affinity=-50).affinity, AFFINITY_MIN)


class LevelTests(unittest.TestCase):
    def test_level_boundaries(self):
        self.assertEqual(affinity_level(0), "distant")
        self.assertEqual(affinity_level(19), "distant")
        self.assertEqual(affinity_level(20), "reserved")
        self.assertEqual(affinity_level(50), "neutral")
        self.assertEqual(affinity_level(70), "friendly")
        self.assertEqual(affinity_level(100), "close")

    def test_labels_bilingual(self):
        self.assertEqual(affinity_label(90, "en"), "close")
        self.assertEqual(affinity_label(90, "ja"), "親友")

    def test_tracker_level_and_label(self):
        m = MoodTracker(affinity=85)
        self.assertEqual(m.level, "close")
        self.assertEqual(m.label("en"), "close")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.path = os.path.join(self._tmp, "mood.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_load_roundtrip(self):
        m = MoodTracker(affinity=72.5, interactions=4)
        self.assertTrue(m.save(self.path))
        loaded = MoodTracker.load(self.path)
        self.assertEqual(loaded.affinity, 72.5)
        self.assertEqual(loaded.interactions, 4)

    def test_save_creates_parent_dirs(self):
        nested = os.path.join(self._tmp, "a", "b", "mood.json")
        self.assertTrue(MoodTracker(affinity=60).save(nested))
        self.assertTrue(os.path.exists(nested))

    def test_load_missing_returns_default(self):
        m = MoodTracker.load(os.path.join(self._tmp, "nope.json"))
        self.assertEqual(m.affinity, AFFINITY_START)

    def test_load_corrupt_returns_default(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ broken")
        m = MoodTracker.load(self.path)
        self.assertEqual(m.affinity, AFFINITY_START)

    def test_saved_file_is_valid_json(self):
        MoodTracker(affinity=33).save(self.path)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["affinity"], 33)


class DecayTests(unittest.TestCase):
    def test_decay_reduces_affinity(self):
        m = MoodTracker(affinity=80, interactions=5)
        delta = m.decay(3600)  # 1 hour
        self.assertLess(delta, 0)
        self.assertLess(m.affinity, 80)

    def test_decay_zero_seconds_no_change(self):
        m = MoodTracker(affinity=80, interactions=5)
        delta = m.decay(0)
        self.assertEqual(delta, 0.0)
        self.assertEqual(m.affinity, 80)

    def test_decay_no_interactions_no_change(self):
        m = MoodTracker(affinity=80, interactions=0)
        delta = m.decay(7200)
        self.assertEqual(delta, 0.0)
        self.assertEqual(m.affinity, 80)

    def test_decay_does_not_go_below_zero(self):
        m = MoodTracker(affinity=1, interactions=10)
        m.decay(1_000_000)
        self.assertGreaterEqual(m.affinity, AFFINITY_MIN)

    def test_decay_custom_rate(self):
        m = MoodTracker(affinity=60, interactions=3)
        m.decay(3600, rate_per_hour=4.0)  # -4 after 1h
        self.assertAlmostEqual(m.affinity, 56.0, places=5)

    def test_auto_decay_no_timestamp_no_change(self):
        m = MoodTracker(affinity=70, interactions=5, last_interaction_time=0.0)
        delta = m.auto_decay()
        self.assertEqual(delta, 0.0)
        self.assertEqual(m.affinity, 70)

    def test_auto_decay_recent_interaction_small_change(self):
        import time
        m = MoodTracker(affinity=70, interactions=5,
                        last_interaction_time=time.time() - 3600)
        delta = m.auto_decay()
        self.assertLess(delta, 0)
        self.assertLess(m.affinity, 70)

    def test_register_updates_last_interaction_time(self):
        import time
        before = time.time()
        m = MoodTracker()
        m.register("hello")
        self.assertGreaterEqual(m._last_interaction_time, before)

    def test_last_interaction_time_persists_in_to_dict(self):
        import time
        m = MoodTracker(interactions=1, last_interaction_time=12345.0)
        d = m.to_dict()
        self.assertAlmostEqual(d["last_interaction_time"], 12345.0)

    def test_last_interaction_time_roundtrips_through_from_dict(self):
        m = MoodTracker(interactions=2, last_interaction_time=99999.0)
        loaded = MoodTracker.from_dict(m.to_dict())
        self.assertAlmostEqual(loaded._last_interaction_time, 99999.0)


class ConfigOverrideTests(unittest.TestCase):
    def test_custom_keywords_and_deltas(self):
        cfg = {
            "positive": {"en": ["yay"]},
            "negative": {"en": ["ugh"]},
            "positive_delta": 7.0,
            "negative_delta": 9.0,
        }
        m = MoodTracker.load(None, mood_config=cfg)
        m.register("yay")
        self.assertEqual(m.affinity, AFFINITY_START + 7.0)
        m2 = MoodTracker.load(None, mood_config=cfg)
        m2.register("ugh")
        self.assertEqual(m2.affinity, AFFINITY_START - 9.0)

    def test_invalid_config_ignored(self):
        m = MoodTracker.load(None, mood_config="not a dict")  # type: ignore[arg-type]
        # Falls back to defaults; known default word still works
        m.register("ありがとう")
        self.assertGreater(m.affinity, AFFINITY_START)


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_mood_tracker()

    def test_singleton_shared(self):
        reset_mood_tracker()
        a = get_mood_tracker(path=os.path.join(tempfile.mkdtemp(), "m.json"))
        b = get_mood_tracker()
        self.assertIs(a, b)

    def test_reset_creates_new(self):
        tmp = tempfile.mkdtemp()
        a = get_mood_tracker(path=os.path.join(tmp, "m.json"))
        reset_mood_tracker()
        b = get_mood_tracker(path=os.path.join(tmp, "m.json"))
        self.assertIsNot(a, b)


if __name__ == "__main__":
    unittest.main()
