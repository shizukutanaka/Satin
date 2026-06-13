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
    check_level_milestone,
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


class MoodHistoryTests(unittest.TestCase):
    """Tests for snapshot_to_history() and load_mood_history()."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._history_path = os.path.join(self._tmp, "mood_history.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_tracker(self, affinity=60.0, interactions=5):
        return MoodTracker(affinity=affinity, interactions=interactions)

    def test_snapshot_creates_file(self):
        t = self._make_tracker()
        t.snapshot_to_history(self._history_path)
        self.assertTrue(os.path.exists(self._history_path))

    def test_snapshot_writes_correct_fields(self):
        t = self._make_tracker(affinity=75.0, interactions=3)
        t.snapshot_to_history(self._history_path)
        from mood import load_mood_history
        entries = load_mood_history(self._history_path)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertIn("date", e)
        self.assertAlmostEqual(e["affinity"], 75.0, places=1)
        self.assertEqual(e["interactions"], 3)
        self.assertIn("level", e)

    def test_same_day_snapshot_updates_not_appends(self):
        t = self._make_tracker(affinity=60.0)
        t.snapshot_to_history(self._history_path)
        t.affinity = 80.0  # update same day
        t.snapshot_to_history(self._history_path)
        from mood import load_mood_history
        entries = load_mood_history(self._history_path)
        self.assertEqual(len(entries), 1)
        self.assertAlmostEqual(entries[0]["affinity"], 80.0, places=1)

    def test_different_day_appends(self):
        import datetime
        t = self._make_tracker(affinity=60.0)
        # Write a fake yesterday entry
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        with open(self._history_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": yesterday, "affinity": 55.0, "level": "neutral", "interactions": 2, "timestamp": 0.0}) + "\n")
        t.snapshot_to_history(self._history_path)
        from mood import load_mood_history
        entries = load_mood_history(self._history_path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["date"], yesterday)
        self.assertAlmostEqual(entries[1]["affinity"], 60.0, places=1)

    def test_load_history_empty_when_no_file(self):
        from mood import load_mood_history
        entries = load_mood_history(os.path.join(self._tmp, "nonexistent.jsonl"))
        self.assertEqual(entries, [])

    def test_load_history_n_limit(self):
        import datetime
        from mood import load_mood_history
        # Write 10 entries
        with open(self._history_path, "w", encoding="utf-8") as f:
            for i in range(10):
                d = (datetime.date.today() - datetime.timedelta(days=9-i)).isoformat()
                f.write(json.dumps({"date": d, "affinity": 50.0+i, "level": "neutral", "interactions": i, "timestamp": 0.0}) + "\n")
        entries = load_mood_history(self._history_path, n=5)
        self.assertEqual(len(entries), 5)
        # Should be the most recent 5 in ascending order
        self.assertAlmostEqual(entries[-1]["affinity"], 59.0, places=1)

    def test_snapshot_skips_zero_interactions(self):
        """Tracker with 0 interactions should still snapshot (history is always useful)."""
        t = MoodTracker(affinity=50.0, interactions=0)
        result = t.snapshot_to_history(self._history_path)
        self.assertTrue(result)
        from mood import load_mood_history
        entries = load_mood_history(self._history_path)
        self.assertEqual(len(entries), 1)

    def test_default_history_path_is_in_config_dir(self):
        from mood import _default_mood_history_path
        path = _default_mood_history_path()
        self.assertIn("config", path)
        self.assertTrue(path.endswith(".jsonl"))


class MoodConfigLoadTests(unittest.TestCase):
    """Tests for _default_mood_config_path and _load_mood_config."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        import mood
        mood.reset_mood_tracker()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        import mood
        mood.reset_mood_tracker()

    def test_default_mood_config_path_in_config_dir(self):
        from mood import _default_mood_config_path
        path = _default_mood_config_path()
        self.assertIn("config", path)
        self.assertTrue(path.endswith("mood_config.json"))

    def test_load_mood_config_missing_file_returns_none(self):
        from mood import _load_mood_config
        result = _load_mood_config(os.path.join(self._tmp, "nonexistent.json"))
        self.assertIsNone(result)

    def test_load_mood_config_invalid_json_returns_none(self):
        from mood import _load_mood_config
        bad = os.path.join(self._tmp, "bad.json")
        with open(bad, "w") as f:
            f.write("{ not valid json ")
        self.assertIsNone(_load_mood_config(bad))

    def test_load_mood_config_non_dict_returns_none(self):
        from mood import _load_mood_config
        arr_file = os.path.join(self._tmp, "arr.json")
        with open(arr_file, "w") as f:
            import json
            json.dump([1, 2, 3], f)
        self.assertIsNone(_load_mood_config(arr_file))

    def test_load_mood_config_valid_file_returns_dict(self):
        from mood import _load_mood_config
        cfg = {"positive_delta": 5.0, "positive": {"en": ["love"]}}
        p = os.path.join(self._tmp, "cfg.json")
        with open(p, "w", encoding="utf-8") as f:
            import json
            json.dump(cfg, f)
        result = _load_mood_config(p)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["positive_delta"], 5.0)

    def test_get_mood_tracker_auto_loads_mood_config(self):
        """get_mood_tracker() with no args should use mood_config.json keywords."""
        import json
        cfg = {
            "positive": {"en": ["superunique_pos_word"]},
            "negative": {"en": ["superunique_neg_word"]},
            "positive_delta": 10.0,
            "negative_delta": 10.0,
        }
        cfg_path = os.path.join(self._tmp, "mood_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        from unittest import mock
        import mood as mood_mod
        with mock.patch.object(mood_mod, "_default_mood_config_path", return_value=cfg_path), \
             mock.patch.object(mood_mod, "_default_mood_path", return_value=os.path.join(self._tmp, "mood.json")):
            tracker = mood_mod.get_mood_tracker()

        before = tracker.affinity
        tracker.register("superunique_pos_word is here")
        self.assertGreater(tracker.affinity, before)

    def test_get_mood_tracker_explicit_config_skips_auto_load(self):
        """Explicitly passing mood_config bypasses auto-loading mood_config.json."""
        import json
        from unittest import mock
        import mood as mood_mod

        explicit_cfg = {
            "positive": {"en": ["explicit_positive_word"]},
            "negative": {"en": []},
            "positive_delta": 15.0,
            "negative_delta": 0.0,
        }
        with mock.patch.object(mood_mod, "_default_mood_path",
                               return_value=os.path.join(self._tmp, "mood.json")):
            tracker = mood_mod.get_mood_tracker(mood_config=explicit_cfg)

        before = tracker.affinity
        tracker.register("explicit_positive_word here")
        self.assertGreater(tracker.affinity, before)


class LevelMilestoneTests(unittest.TestCase):
    def test_no_change_within_level_returns_none(self):
        # 61 and 62 are both "friendly" (60-80)
        self.assertIsNone(check_level_milestone(61.0, 62.0))

    def test_level_up_crossing_boundary(self):
        result = check_level_milestone(59.0, 61.0)  # neutral → friendly
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "up")
        self.assertEqual(result["from_level"], "neutral")
        self.assertEqual(result["to_level"], "friendly")

    def test_level_down_crossing_boundary(self):
        result = check_level_milestone(61.0, 59.0)  # friendly → neutral
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "down")
        self.assertEqual(result["from_level"], "friendly")
        self.assertEqual(result["to_level"], "neutral")

    def test_message_is_nonempty_string(self):
        result = check_level_milestone(19.0, 21.0)  # distant → reserved
        self.assertIsInstance(result["message"], str)
        self.assertGreater(len(result["message"]), 0)

    def test_english_message(self):
        result = check_level_milestone(59.0, 61.0, lang="en")
        self.assertIsNotNone(result)
        self.assertIsInstance(result["message"], str)

    def test_equal_values_returns_none(self):
        self.assertIsNone(check_level_milestone(50.0, 50.0))

    def test_multi_level_jump_up(self):
        result = check_level_milestone(10.0, 85.0)  # distant → close
        self.assertEqual(result["direction"], "up")
        self.assertEqual(result["to_level"], "close")

    def test_has_all_expected_keys(self):
        result = check_level_milestone(39.0, 41.0)  # reserved → neutral
        for key in ("direction", "from_level", "to_level", "message"):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
