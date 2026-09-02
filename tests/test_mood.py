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

import pytest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import time  # noqa: E402

import mood  # noqa: E402
from mood import (  # noqa: E402
    AFFINITY_MAX,
    AFFINITY_MIN,
    AFFINITY_START,
    MoodTracker,
    affinity_label,
    affinity_level,
    check_level_milestone,
    check_confession_event,
    check_hurt_event,
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


class AdjustTests(unittest.TestCase):
    def test_adjust_adds_affinity(self):
        m = MoodTracker(affinity=50)
        delta = m.adjust(8)
        self.assertEqual(delta, 8.0)
        self.assertEqual(m.affinity, 58)

    def test_adjust_negative(self):
        m = MoodTracker(affinity=50)
        m.adjust(-10)
        self.assertEqual(m.affinity, 40)

    def test_adjust_clamps_high(self):
        m = MoodTracker(affinity=98)
        m.adjust(50)
        self.assertEqual(m.affinity, 100)

    def test_adjust_clamps_low(self):
        m = MoodTracker(affinity=3)
        m.adjust(-50)
        self.assertEqual(m.affinity, 0)

    def test_adjust_invalid_is_noop(self):
        m = MoodTracker(affinity=50)
        self.assertEqual(m.adjust("nope"), 0.0)
        self.assertEqual(m.affinity, 50)

    def test_adjust_does_not_touch_interactions(self):
        m = MoodTracker(affinity=50, interactions=3)
        m.adjust(5)
        self.assertEqual(m.interactions, 3)


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

    def test_auto_decay_advances_checkpoint(self):
        import time
        m = MoodTracker(affinity=70, interactions=5,
                        last_interaction_time=time.time() - 3600)
        m.auto_decay()
        # Checkpoint must move to ~now so the elapsed window isn't recounted.
        self.assertGreater(m._last_interaction_time, time.time() - 5)

    def test_auto_decay_twice_does_not_double_decay(self):
        # Regression: toggling autonomous on/off called auto_decay repeatedly,
        # each time decaying the SAME elapsed period from a stale timestamp.
        import time
        m = MoodTracker(affinity=80, interactions=5,
                        last_interaction_time=time.time() - 7200)  # 2h idle
        first = m.auto_decay()
        after_first = m.affinity
        second = m.auto_decay()  # immediately again, no register() in between
        self.assertLess(first, 0)                    # first call decays
        self.assertAlmostEqual(second, 0.0, places=2)  # second is ~no-op
        self.assertAlmostEqual(m.affinity, after_first, places=2)

    def test_register_updates_last_interaction_time(self):
        import time
        before = time.time()
        m = MoodTracker()
        m.register("hello")
        self.assertGreaterEqual(m._last_interaction_time, before)

    def test_last_interaction_time_persists_in_to_dict(self):
        m = MoodTracker(interactions=1, last_interaction_time=12345.0)
        d = m.to_dict()
        self.assertAlmostEqual(d["last_interaction_time"], 12345.0)

    def test_last_interaction_time_roundtrips_through_from_dict(self):
        m = MoodTracker(interactions=2, last_interaction_time=99999.0)
        loaded = MoodTracker.from_dict(m.to_dict())
        self.assertAlmostEqual(loaded._last_interaction_time, 99999.0)


class ConfigOverrideTests(unittest.TestCase):
    def test_custom_keywords_and_deltas(self):
        # delta 自体の検証なので日次上限（既定 5.0）を外す。
        # 上限の検証は DailyGainCapTests の担当。
        cfg = {
            "positive": {"en": ["yay"]},
            "negative": {"en": ["ugh"]},
            "positive_delta": 7.0,
            "negative_delta": 9.0,
            "max_daily_gain": 100.0,
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

    def test_snapshot_file_is_owner_only(self):
        import stat
        t = self._make_tracker()
        t.snapshot_to_history(self._history_path)
        mode = stat.S_IMODE(os.stat(self._history_path).st_mode)
        self.assertEqual(mode & 0o077, 0, "mood history must not be group/other readable")

    def test_save_file_is_owner_only(self):
        import stat
        path = os.path.join(self._tmp, "mood.json")
        self._make_tracker().save(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode & 0o077, 0, "mood.json must not be group/other readable")

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

    @pytest.mark.real_paths
    def test_default_history_path_is_in_config_dir(self):
        from mood import _default_mood_history_path
        path = _default_mood_history_path()
        self.assertIn("config", path)
        self.assertTrue(path.endswith(".jsonl"))

    def test_corrupt_last_line_same_day_appends_not_overwrites(self):
        """Regression: malformed JSON in last line must not cause duplicate entry.

        Before the fix, json.JSONDecodeError from lines[-2] fell through to the
        outer except block, triggering lines.append() instead of lines[-1]=,
        producing a second entry for the same day.
        """
        import gzip as _gz  # noqa — only to confirm no import leaks
        today = __import__("datetime").date.today().isoformat()
        # Seed with one today-entry that is corrupt JSON
        with open(self._history_path, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_NOT_JSON\n")
        t = self._make_tracker(affinity=70.0)
        t.snapshot_to_history(self._history_path)
        from mood import load_mood_history
        entries = load_mood_history(self._history_path)
        # Corrupt line is not valid JSON → skipped by load_mood_history; today entry appended once
        today_entries = [e for e in entries if e.get("date") == today]
        self.assertEqual(len(today_entries), 1,
                         f"Expected exactly 1 today-entry, got: {today_entries}")

    def test_repeated_snapshots_produce_no_blank_lines(self):
        """Regression: readlines() retains \\n; joining with \\n doubled blank lines.

        After repeated snapshots the file must contain no blank lines.
        """
        import datetime
        t = self._make_tracker(affinity=60.0)
        t.snapshot_to_history(self._history_path)
        t.affinity = 65.0
        t.snapshot_to_history(self._history_path)
        # Add a second-day entry to verify multi-line write path
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        with open(self._history_path, "w", encoding="utf-8") as f:
            f.write('{"date": "' + yesterday + '", "affinity": 55.0, "level": "neutral", "interactions": 2, "timestamp": 0.0}\n')
        t.affinity = 70.0
        t.snapshot_to_history(self._history_path)
        t.affinity = 75.0
        t.snapshot_to_history(self._history_path)
        with open(self._history_path, encoding="utf-8") as f:
            raw = f.read()
        blank_lines = [ln for ln in raw.splitlines() if ln.strip() == ""]
        self.assertEqual(blank_lines, [],
                         f"No blank lines expected; file content:\n{raw!r}")


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

    def test_bundled_mood_config_treats_goodnight_as_positive(self):
        """Shipped mood_config.json should give affinity for おやすみ / good night."""
        import json
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "mood_config.json",
        )
        with open(repo_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
        tracker = MoodTracker.load(None, mood_config=cfg)
        before = tracker.affinity
        tracker.register("おやすみ")
        self.assertGreater(tracker.affinity, before)
        tracker2 = MoodTracker.load(None, mood_config=cfg)
        before2 = tracker2.affinity
        tracker2.register("good night")
        self.assertGreater(tracker2.affinity, before2)

    def test_bundled_mood_config_treats_apology_as_positive(self):
        """Shipped mood_config.json should give affinity for ごめん / sorry (healing)."""
        import json
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "mood_config.json",
        )
        with open(repo_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
        t = MoodTracker.load(None, mood_config=cfg)
        t.affinity = 15.0  # distant
        before = t.affinity
        t.register("ごめんね")
        self.assertGreater(t.affinity, before)
        t2 = MoodTracker.load(None, mood_config=cfg)
        t2.affinity = 15.0
        before2 = t2.affinity
        t2.register("I'm so sorry")
        self.assertGreater(t2.affinity, before2)

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


class TransitionMessageTests(unittest.TestCase):
    """stage-specific transition messages differ per from→to pair."""

    def _msg(self, before, after, lang="ja"):
        return check_level_milestone(before, after, lang=lang)["message"]

    def _all_candidates(self, before, after, lang="ja"):
        from mood import _TRANSITION_MESSAGES
        fl = check_level_milestone(before, after, lang)["from_level"]
        tl = check_level_milestone(before, after, lang)["to_level"]
        key = f"{fl}→{tl}"
        if key not in _TRANSITION_MESSAGES:
            return None
        return _TRANSITION_MESSAGES[key][lang]

    def test_distant_to_reserved_ja(self):
        candidates = self._all_candidates(19.0, 21.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(19.0, 21.0, "ja"), candidates)

    def test_reserved_to_neutral_ja(self):
        candidates = self._all_candidates(39.0, 41.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(39.0, 41.0, "ja"), candidates)

    def test_neutral_to_friendly_ja(self):
        candidates = self._all_candidates(59.0, 61.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(59.0, 61.0, "ja"), candidates)

    def test_friendly_to_close_ja(self):
        candidates = self._all_candidates(79.0, 81.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(79.0, 81.0, "ja"), candidates)

    def test_close_to_friendly_down_ja(self):
        candidates = self._all_candidates(81.0, 79.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(81.0, 79.0, "ja"), candidates)

    def test_friendly_to_neutral_down_ja(self):
        candidates = self._all_candidates(61.0, 59.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(61.0, 59.0, "ja"), candidates)

    def test_neutral_to_reserved_down_ja(self):
        candidates = self._all_candidates(41.0, 39.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(41.0, 39.0, "ja"), candidates)

    def test_reserved_to_distant_down_ja(self):
        candidates = self._all_candidates(21.0, 19.0, "ja")
        self.assertIsNotNone(candidates)
        self.assertIn(self._msg(21.0, 19.0, "ja"), candidates)

    def test_all_transitions_en(self):
        pairs = [(19.0, 21.0), (39.0, 41.0), (59.0, 61.0), (79.0, 81.0)]
        for before, after in pairs:
            msg = self._msg(before, after, "en")
            candidates = self._all_candidates(before, after, "en")
            self.assertIn(msg, candidates, f"{before}→{after} en not in candidates")

    def test_multi_level_jump_uses_generic_fallback(self):
        # distant→close: no specific entry; falls back to generic level_up
        from mood import _MILESTONE_MESSAGES, _TRANSITION_MESSAGES
        result = check_level_milestone(10.0, 85.0, lang="ja")
        key = f"{result['from_level']}→{result['to_level']}"
        if key not in _TRANSITION_MESSAGES:
            self.assertIn(result["message"], _MILESTONE_MESSAGES["level_up"]["ja"])

    def test_messages_are_nonempty_strings(self):
        pairs = [(19.0, 21.0), (39.0, 41.0), (59.0, 61.0), (79.0, 81.0),
                 (81.0, 79.0), (61.0, 59.0), (41.0, 39.0), (21.0, 19.0)]
        for b, a in pairs:
            self.assertGreater(len(self._msg(b, a)), 0, f"{b}→{a}")


class ConfessionEventTests(unittest.TestCase):
    """check_confession_event は close 到達 + 実体のある関係で 1 度だけ発火する。

    既定では出会いから 7 日・対話 20 回を要求する（love-bombing 防止。
    詳細は ConfessionMinimumRelationshipTests と mood.check_confession_event
    の docstring）。このクラスは発火そのものを見たいので、_tracker() が
    条件を満たした状態を作る。
    """

    def _tracker(self, affinity=79.0, confession_done=False):
        import time as _t
        t = MoodTracker(affinity=affinity,
                        interactions=50,
                        first_interaction_time=_t.time() - 30 * 86400)
        t._confession_done = confession_done
        return t

    def test_returns_none_when_not_friendly_to_close(self):
        t = self._tracker(affinity=59.0)
        self.assertIsNone(check_confession_event(t, 59.0, 61.0))  # neutral→friendly

    def test_returns_none_when_already_done(self):
        t = self._tracker(affinity=80.0, confession_done=True)
        result = check_confession_event(t, 79.0, 81.0)
        self.assertIsNone(result)

    def test_returns_message_on_first_crossing_ja(self):
        t = self._tracker(affinity=79.0)
        from mood import _CONFESSION_MESSAGES
        msg = check_confession_event(t, 79.0, 81.0, lang="ja")
        self.assertIsNotNone(msg)
        self.assertIn(msg, _CONFESSION_MESSAGES["ja"])

    def test_returns_message_on_first_crossing_en(self):
        t = self._tracker(affinity=79.0)
        from mood import _CONFESSION_MESSAGES
        msg = check_confession_event(t, 79.0, 81.0, lang="en")
        self.assertIsNotNone(msg)
        self.assertIn(msg, _CONFESSION_MESSAGES["en"])

    def test_marks_confession_done_after_first_call(self):
        t = self._tracker(affinity=79.0)
        self.assertFalse(t._confession_done)
        check_confession_event(t, 79.0, 81.0)
        self.assertTrue(t._confession_done)

    def test_returns_none_on_second_call(self):
        t = self._tracker(affinity=79.0)
        check_confession_event(t, 79.0, 81.0)
        result = check_confession_event(t, 79.0, 81.0)
        self.assertIsNone(result)

    def test_returns_none_when_level_down(self):
        t = self._tracker(affinity=81.0)
        result = check_confession_event(t, 81.0, 79.0)  # close→friendly (down)
        self.assertIsNone(result)

    def test_confession_done_roundtrips(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        path = os.path.join(d, "mood.json")
        try:
            t = MoodTracker(affinity=80.0, confession_done=True)
            t.save(path)
            t2 = MoodTracker.load(path)
            self.assertTrue(t2._confession_done)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_confession_default_is_false(self):
        t = MoodTracker(affinity=30.0)
        self.assertFalse(t._confession_done)

    def test_confession_done_false_roundtrips(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        path = os.path.join(d, "mood.json")
        try:
            t = MoodTracker(affinity=50.0, confession_done=False)
            t.save(path)
            t2 = MoodTracker.load(path)
            self.assertFalse(t2._confession_done)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class ConfessionGetAttrDefaultTests(unittest.TestCase):
    """Regression: getattr(tracker, '_confession_done', True) used True as default,
    so a tracker loaded from old state without that attribute would silently
    skip every confession forever. Default must be False."""

    def _old_format_tracker(self):
        """_confession_done を持たない旧形式の tracker を模す。

        告白の最低条件（7 日・20 回）は満たした状態にする。このクラスの
        subject はあくまで `_confession_done` の既定値であって、最低条件では
        ないため、そちらを未達にすると何を検証しているのか分からなくなる。
        `object.__new__` は `__init__` を通らないので `confession_min_*` も
        存在しない — check_confession_event がモジュール定数へフォールバック
        することの検証も兼ねる。
        """
        import time as _t
        from mood import MoodTracker
        t = object.__new__(MoodTracker)
        t.affinity = 81.0
        t.interactions = 50
        t._first_interaction_time = _t.time() - 30 * 86400
        # 意図的に t._confession_done は設定しない。
        return t

    def test_tracker_without_attribute_shows_confession(self):
        from mood import check_confession_event
        msg = check_confession_event(self._old_format_tracker(), 79.0, 81.0, lang="ja")
        self.assertIsNotNone(msg, "tracker with no _confession_done must show confession")

    def test_tracker_without_attribute_marks_done_after_call(self):
        from mood import check_confession_event
        t = self._old_format_tracker()
        check_confession_event(t, 79.0, 81.0)
        self.assertTrue(t._confession_done)


class LevelTransitionHistoryTests(unittest.TestCase):
    """snapshot_to_history() records level_changed milestones."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._history = os.path.join(self._tmp, "mood_history.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_entry(self, affinity: float, level: str, date_str: str) -> None:
        """ファイルに過去エントリを直接書き込む（日付固定のためモックの代替）。"""
        entry = {"date": date_str, "timestamp": 0.0, "affinity": affinity,
                 "level": level, "interactions": 1}
        with open(self._history, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def test_no_level_change_has_no_flag(self):
        # 前日のエントリ: neutral
        self._write_entry(50.0, "neutral", "2026-01-01")
        # 今日: still neutral
        t = MoodTracker(affinity=55.0, interactions=1)
        t.snapshot_to_history(self._history)
        from mood import load_mood_history
        entries = load_mood_history(self._history)
        self.assertEqual(len(entries), 2)
        self.assertNotIn("level_changed", entries[1])

    def test_level_up_sets_flag(self):
        self._write_entry(55.0, "neutral", "2026-01-01")
        t = MoodTracker(affinity=65.0, interactions=1)  # friendly
        t.snapshot_to_history(self._history)
        from mood import load_mood_history
        entries = load_mood_history(self._history)
        self.assertTrue(entries[1].get("level_changed"))
        self.assertEqual(entries[1].get("prev_level"), "neutral")
        self.assertEqual(entries[1].get("level"), "friendly")

    def test_level_down_sets_flag(self):
        self._write_entry(65.0, "friendly", "2026-01-01")
        t = MoodTracker(affinity=45.0, interactions=1)  # neutral
        t.snapshot_to_history(self._history)
        from mood import load_mood_history
        entries = load_mood_history(self._history)
        self.assertTrue(entries[1].get("level_changed"))
        self.assertEqual(entries[1].get("prev_level"), "friendly")
        self.assertEqual(entries[1].get("level"), "neutral")

    def test_first_entry_never_has_flag(self):
        t = MoodTracker(affinity=70.0, interactions=1)
        t.snapshot_to_history(self._history)
        from mood import load_mood_history
        entries = load_mood_history(self._history)
        self.assertNotIn("level_changed", entries[0])

    def test_load_level_transitions_filters_correctly(self):
        self._write_entry(50.0, "neutral", "2026-01-01")
        self._write_entry(55.0, "neutral", "2026-01-02")  # no change
        self._write_entry(65.0, "friendly", "2026-01-03")  # no flag (written directly)
        # Write a transition entry manually
        entry_with_flag = {"date": "2026-01-03", "timestamp": 0.0, "affinity": 65.0,
                           "level": "friendly", "interactions": 3,
                           "level_changed": True, "prev_level": "neutral"}
        # Rewrite file with the transition entry at day 3
        import datetime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        with open(self._history, "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-01-01", "timestamp": 0.0, "affinity": 50.0,
                                "level": "neutral", "interactions": 1}) + "\n")
            f.write(json.dumps({"date": "2026-01-02", "timestamp": 0.0, "affinity": 55.0,
                                "level": "neutral", "interactions": 2}) + "\n")
            f.write(json.dumps(entry_with_flag) + "\n")
            f.write(json.dumps({"date": "2026-01-04", "timestamp": 0.0, "affinity": 68.0,
                                "level": "friendly", "interactions": 4}) + "\n")
        from mood import load_level_transitions
        transitions = load_level_transitions(self._history)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["prev_level"], "neutral")
        self.assertEqual(transitions[0]["level"], "friendly")

    def test_load_level_transitions_empty_when_no_history(self):
        from mood import load_level_transitions
        self.assertEqual(load_level_transitions(self._history), [])

    def test_same_day_update_preserves_transition_flag(self):
        """前日 neutral → 今日 friendly が検出され、同日再書き込みでもフラグが残る。"""
        self._write_entry(50.0, "neutral", "2026-01-01")
        t_up = MoodTracker(affinity=65.0, interactions=2)  # friendly — level up
        t_up.snapshot_to_history(self._history)
        # 同日更新（好感度が少し変わった）
        t_up.affinity = 67.0
        t_up.snapshot_to_history(self._history)
        from mood import load_mood_history, load_level_transitions
        entries = load_mood_history(self._history)
        # 2 エントリのまま（前日 + 今日）
        self.assertEqual(len(entries), 2)
        # マイルストーンは維持されている
        transitions = load_level_transitions(self._history)
        self.assertEqual(len(transitions), 1)


class AbsenceMessageTests(unittest.TestCase):
    """Tests for absence_message() shared helper."""

    def setUp(self):
        reset_mood_tracker()

    def tearDown(self):
        reset_mood_tracker()

    def _make_tracker(self, last_ts: float, interactions: int = 5) -> MoodTracker:
        t = MoodTracker(interactions=interactions)
        t._last_interaction_time = last_ts
        return t

    def test_no_message_when_interactions_zero(self):
        from mood import absence_message
        t = self._make_tracker(last_ts=0.0, interactions=0)
        self.assertEqual(absence_message(t), "")

    def test_no_message_when_last_ts_zero(self):
        from mood import absence_message
        t = self._make_tracker(last_ts=0.0, interactions=3)
        self.assertEqual(absence_message(t), "")

    def test_no_message_when_less_than_24h(self):
        import time
        from mood import absence_message
        t = self._make_tracker(last_ts=time.time() - 3600)  # 1h ago
        self.assertEqual(absence_message(t), "")

    def test_message_when_25h_absent_ja(self):
        import time
        from mood import absence_message
        t = self._make_tracker(last_ts=time.time() - 25 * 3600)
        msg = absence_message(t, lang="ja")
        self.assertIn("昨日", msg)
        self.assertGreater(len(msg), 0)

    def test_message_when_25h_absent_en(self):
        import time
        from mood import absence_message
        t = self._make_tracker(last_ts=time.time() - 25 * 3600)
        msg = absence_message(t, lang="en")
        self.assertIn("missed", msg)
        self.assertGreater(len(msg), 0)

    def test_message_multiple_days_ja(self):
        import time
        from mood import absence_message
        t = self._make_tracker(last_ts=time.time() - 72 * 3600)  # 3 days
        msg = absence_message(t, lang="ja")
        self.assertIn("3日", msg)

    def test_message_multiple_days_en(self):
        import time
        from mood import absence_message
        t = self._make_tracker(last_ts=time.time() - 72 * 3600)  # 3 days
        msg = absence_message(t, lang="en")
        self.assertIn("3 days", msg)

    def test_distant_level_gives_neutral_reply_ja(self):
        import time
        from mood import absence_message
        t = MoodTracker(affinity=10.0, interactions=5)
        t._last_interaction_time = time.time() - 25 * 3600
        msg = absence_message(t, lang="ja")
        self.assertGreater(len(msg), 0)
        self.assertNotIn("会いたかった", msg)  # distant should not express longing

    def test_close_level_gives_emotional_reply_ja(self):
        import time
        from mood import absence_message
        t = MoodTracker(affinity=90.0, interactions=5)
        t._last_interaction_time = time.time() - 25 * 3600
        msg = absence_message(t, lang="ja")
        self.assertGreater(len(msg), 0)
        # Close-level message should convey strong feeling
        self.assertTrue(
            any(w in msg for w in ["寂し", "待ってた", "会いたかった"]),
            f"Expected emotional wording for close level; got: {msg!r}"
        )

    def test_close_level_multi_day_en(self):
        import time
        from mood import absence_message
        t = MoodTracker(affinity=90.0, interactions=5)
        t._last_interaction_time = time.time() - 72 * 3600  # 3 days
        msg = absence_message(t, lang="en")
        self.assertGreater(len(msg), 0)
        self.assertTrue(
            any(w in msg for w in ["waited", "glad", "missed"]),
            f"Expected emotional wording for close level; got: {msg!r}"
        )

    def test_reserved_level_gives_brief_reply_ja(self):
        import time
        from mood import absence_message
        t = MoodTracker(affinity=30.0, interactions=5)
        t._last_interaction_time = time.time() - 25 * 3600
        msg = absence_message(t, lang="ja")
        self.assertGreater(len(msg), 0)


class FirstInteractionTimeTests(unittest.TestCase):
    """register() records the relationship start; it round-trips through to_dict."""

    def setUp(self):
        reset_mood_tracker()

    def tearDown(self):
        reset_mood_tracker()

    def test_register_sets_first_interaction_time(self):
        m = MoodTracker()
        self.assertEqual(m._first_interaction_time, 0.0)
        m.register("hello")
        self.assertGreater(m._first_interaction_time, 0.0)

    def test_first_interaction_time_does_not_change_on_second_register(self):
        m = MoodTracker()
        m.register("hello")
        first = m._first_interaction_time
        m.register("again")
        self.assertEqual(m._first_interaction_time, first)

    def test_first_interaction_time_roundtrips(self):
        m = MoodTracker()
        m.register("hi")
        loaded = MoodTracker.from_dict(m.to_dict())
        self.assertEqual(loaded._first_interaction_time, m._first_interaction_time)

    def test_last_anniversary_days_roundtrips(self):
        m = MoodTracker()
        m._last_anniversary_days = 30
        loaded = MoodTracker.from_dict(m.to_dict())
        self.assertEqual(loaded._last_anniversary_days, 30)


class AnniversaryMessageTests(unittest.TestCase):
    """Tests for anniversary_message() shared helper."""

    def setUp(self):
        reset_mood_tracker()

    def tearDown(self):
        reset_mood_tracker()

    def _make_tracker(self, days_ago: float, interactions: int = 5) -> MoodTracker:
        import time
        t = MoodTracker(interactions=interactions)
        t._first_interaction_time = time.time() - days_ago * 86400
        return t

    def test_no_message_before_first_milestone(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=3)
        self.assertEqual(anniversary_message(t), "")

    def test_no_message_when_interactions_zero(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=30, interactions=0)
        self.assertEqual(anniversary_message(t), "")

    def test_no_message_when_first_ts_zero(self):
        from mood import anniversary_message
        t = MoodTracker(interactions=5)
        t._first_interaction_time = 0.0
        self.assertEqual(anniversary_message(t), "")

    def test_message_at_7_days_ja(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=7)
        msg = anniversary_message(t, lang="ja")
        self.assertIn("7日", msg)

    def test_message_at_30_days_en(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=35)
        msg = anniversary_message(t, lang="en")
        self.assertIn("30 days", msg)

    def test_one_year_message_ja(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=365)
        msg = anniversary_message(t, lang="ja")
        self.assertIn("1年", msg)

    def test_two_year_message_en(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=730)
        msg = anniversary_message(t, lang="en")
        self.assertIn("2 years", msg)

    def test_same_milestone_not_repeated(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=30)
        first = anniversary_message(t, lang="ja")
        self.assertNotEqual(first, "")
        second = anniversary_message(t, lang="ja")
        self.assertEqual(second, "")

    def test_marker_advances_to_milestone(self):
        from mood import anniversary_message
        t = self._make_tracker(days_ago=100)
        anniversary_message(t, lang="ja")
        self.assertEqual(t._last_anniversary_days, 100)


class DailyLoginTests(unittest.TestCase):
    """Tests for check_daily_login — daily-first-visit bonus and login streak."""

    def setUp(self):
        from mood import check_daily_login
        self._check = check_daily_login

    def test_first_login_returns_message_and_bonus(self):
        t = MoodTracker(affinity=50.0)
        before = t.affinity
        msg = self._check(t, today="2026-06-16", lang="ja")
        self.assertIsNotNone(msg)
        self.assertGreater(t.affinity, before)
        self.assertEqual(t._login_streak, 1)
        self.assertEqual(t._last_login_date, "2026-06-16")

    def test_never_says_welcome_back_to_someone_it_has_never_met(self):
        """初回起動で「おかえり」と言わないこと。

        まっさらな状態（好感度ファイルも会話履歴も無い）で起動すると
        「おかえり！今日も会いに来てくれてうれしいな。」と言っていた —
        一度も会ったことのない相手に対してである。

        本製品の価値は「時間をかけて育つ関係」なので、初対面で既に親しい
        ふりをすると、その後の成長が演出でしかなくなる。育っていない親密さを
        演じるのは、別れぎわの引き止め（farewell_integrity）と同種の操作で、
        こちらは関係の入口で起きる。
        """
        for lang, forbidden in (("ja", "おかえり"), ("en", "Welcome back")):
            with self.subTest(lang=lang):
                msg = self._check(MoodTracker(affinity=50.0),
                                  today="2026-06-16", lang=lang)
                self.assertIsNotNone(msg)
                self.assertNotIn(forbidden, msg)

    def test_first_meeting_greets_as_a_first_meeting(self):
        self.assertIn("はじめまして",
                      self._check(MoodTracker(), today="2026-06-16", lang="ja"))
        self.assertIn("nice to meet you",
                      self._check(MoodTracker(), today="2026-06-16", lang="en").lower())

    def test_second_day_is_a_welcome_back_not_a_first_meeting(self):
        """2 日目以降は通常どおり「おかえり」に戻ること。"""
        t = MoodTracker()
        self._check(t, today="2026-06-16", lang="ja")
        msg = self._check(t, today="2026-06-17", lang="ja")
        self.assertIn("おかえり", msg)
        self.assertNotIn("はじめまして", msg)

    def test_existing_user_without_a_login_date_is_not_a_first_meeting(self):
        """_last_login_date 導入前からの既存ユーザーを初対面扱いしないこと。

        判定を _last_login_date だけに頼ると、対話履歴を持つ既存ユーザーに
        「はじめまして」と言ってしまう。相手の記憶を消すほうが、余計に
        「おかえり」と言うより害が大きいので、迷ったら初対面でない側に倒す。
        """
        t = MoodTracker(affinity=72.0)
        t.interactions = 40
        t._first_interaction_time = 1_700_000_000.0
        msg = self._check(t, today="2026-06-16", lang="ja")
        self.assertIn("おかえり", msg)
        self.assertNotIn("はじめまして", msg)

    def test_second_login_same_day_returns_none(self):
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-16", lang="ja")
        affinity_after_first = t.affinity
        msg = self._check(t, today="2026-06-16", lang="ja")
        self.assertIsNone(msg)
        # No additional bonus on the same day
        self.assertEqual(t.affinity, affinity_after_first)

    def test_consecutive_days_increase_streak(self):
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-16", lang="ja")
        self.assertEqual(t._login_streak, 1)
        self._check(t, today="2026-06-17", lang="ja")
        self.assertEqual(t._login_streak, 2)
        self._check(t, today="2026-06-18", lang="ja")
        self.assertEqual(t._login_streak, 3)

    def test_gap_resets_streak(self):
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-16", lang="ja")
        self._check(t, today="2026-06-17", lang="ja")
        self.assertEqual(t._login_streak, 2)
        # Skip a day -> reset to 1
        self._check(t, today="2026-06-19", lang="ja")
        self.assertEqual(t._login_streak, 1)

    def test_streak_milestone_message_at_3(self):
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-16", lang="ja")
        self._check(t, today="2026-06-17", lang="ja")
        msg = self._check(t, today="2026-06-18", lang="ja")
        self.assertIsNotNone(msg)
        self.assertIn("3", msg)

    def test_bonus_capped(self):
        from mood import _DAILY_LOGIN_MAX_BONUS
        t = MoodTracker(affinity=0.0, login_streak=100, last_login_date="2026-06-15")
        before = t.affinity
        self._check(t, today="2026-06-16", lang="ja")
        gained = t.affinity - before
        self.assertLessEqual(gained, _DAILY_LOGIN_MAX_BONUS + 0.001)

    def test_en_message(self):
        # 再訪ユーザーで検証する。まっさらな tracker は初対面あつかいになり、
        # デイリーログインの文言ではなく「はじめまして」を返すため。
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-15", lang="en")   # 初対面をここで消化する
        msg = self._check(t, today="2026-06-16", lang="en")
        self.assertIsNotNone(msg)
        self.assertTrue(any(w in msg.lower() for w in ("welcome", "glad", "day")))

    def test_persistence_roundtrip(self):
        t = MoodTracker(affinity=50.0)
        self._check(t, today="2026-06-16", lang="ja")
        self._check(t, today="2026-06-17", lang="ja")
        data = t.to_dict()
        self.assertEqual(data["login_streak"], 2)
        self.assertEqual(data["last_login_date"], "2026-06-17")
        restored = MoodTracker.from_dict(data)
        self.assertEqual(restored._login_streak, 2)
        self.assertEqual(restored._last_login_date, "2026-06-17")

    def test_corrupt_date_resets_streak_to_one(self):
        t = MoodTracker(affinity=50.0, last_login_date="not-a-date", login_streak=5)
        msg = self._check(t, today="2026-06-16", lang="ja")
        self.assertIsNotNone(msg)
        self.assertEqual(t._login_streak, 1)


class InteractionMilestoneTests(unittest.TestCase):
    """Tests for check_interaction_milestone — cumulative conversation count rewards."""

    def setUp(self):
        from mood import check_interaction_milestone, _INTERACTION_MILESTONE_MESSAGES
        self._check = check_interaction_milestone
        self._msgs = _INTERACTION_MILESTONE_MESSAGES

    def test_fires_at_10_ja(self):
        msg = self._check(9, 10, lang="ja")
        self.assertIsNotNone(msg)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_fires_at_10_en(self):
        msg = self._check(9, 10, lang="en")
        self.assertIsNotNone(msg)
        self.assertGreater(len(msg), 0)

    def test_fires_at_25(self):
        self.assertIsNotNone(self._check(24, 25, lang="ja"))

    def test_fires_at_50(self):
        self.assertIsNotNone(self._check(49, 50, lang="en"))

    def test_fires_at_100(self):
        self.assertIsNotNone(self._check(99, 100, lang="ja"))

    def test_fires_at_200(self):
        self.assertIsNotNone(self._check(199, 200, lang="ja"))

    def test_fires_at_250(self):
        self.assertIsNotNone(self._check(249, 250, lang="en"))

    def test_fires_at_500(self):
        self.assertIsNotNone(self._check(499, 500, lang="ja"))

    def test_fires_at_750(self):
        self.assertIsNotNone(self._check(749, 750, lang="en"))

    def test_fires_at_1000(self):
        self.assertIsNotNone(self._check(999, 1000, lang="en"))

    def test_no_fire_below_first_milestone(self):
        self.assertIsNone(self._check(0, 9, lang="ja"))

    def test_no_fire_above_milestone(self):
        self.assertIsNone(self._check(10, 11, lang="ja"))

    def test_no_fire_at_same_value(self):
        self.assertIsNone(self._check(10, 10, lang="ja"))

    def test_first_milestone_wins_when_multiple_crossed(self):
        # Crosses both 10 and 25; should return a 10-milestone message
        msg = self._check(8, 26, lang="ja")
        self.assertIsNotNone(msg)
        msgs_10 = self._msgs[10]["ja"]
        msgs_25 = self._msgs[25]["ja"]
        self.assertTrue(msg in msgs_10 or msg in msgs_25)
        # The returned message must be from the *first* milestone (10)
        self.assertIn(msg, msgs_10)

    def test_all_milestones_have_ja_and_en(self):
        from mood import _INTERACTION_MILESTONES_SORTED
        for m in _INTERACTION_MILESTONES_SORTED:
            self.assertIn("ja", self._msgs[m], f"milestone {m} missing ja")
            self.assertIn("en", self._msgs[m], f"milestone {m} missing en")
            self.assertGreater(len(self._msgs[m]["ja"]), 0, f"milestone {m} ja empty")
            self.assertGreater(len(self._msgs[m]["en"]), 0, f"milestone {m} en empty")

    def test_region_code_falls_back_to_en(self):
        msg = self._check(9, 10, lang="en-US")
        self.assertIsNotNone(msg)

    def test_unknown_lang_falls_back_to_ja(self):
        msg = self._check(9, 10, lang="fr")
        self.assertIsNotNone(msg)

    def test_returns_string_not_list(self):
        result = self._check(9, 10, lang="ja")
        self.assertIsInstance(result, str)


class HurtEventTests(unittest.TestCase):
    """check_hurt_event() — fires when delta is below the hurt threshold."""

    def test_no_hurt_for_zero_delta(self):
        self.assertIsNone(check_hurt_event(0.0))

    def test_no_hurt_for_small_negative(self):
        self.assertIsNone(check_hurt_event(-1.0))

    def test_no_hurt_exactly_at_threshold(self):
        from mood import _HURT_THRESHOLD
        self.assertIsNone(check_hurt_event(_HURT_THRESHOLD))

    def test_hurt_fires_below_threshold(self):
        from mood import _HURT_THRESHOLD
        result = check_hurt_event(_HURT_THRESHOLD - 0.01)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_hurt_fires_at_max_negative(self):
        result = check_hurt_event(-10.0)
        self.assertIsNotNone(result)

    def test_hurt_for_positive_delta_returns_none(self):
        self.assertIsNone(check_hurt_event(5.0))

    def test_hurt_ja(self):
        result = check_hurt_event(-8.0, lang="ja")
        self.assertIsNotNone(result)
        self.assertTrue(any(c in result for c in "あいうえおかきくけこさしすせそたちつてとなにぬねの"
                                                  "はひふへほまみむめもやゆよらりるれろわをんー"))

    def test_hurt_en(self):
        result = check_hurt_event(-8.0, lang="en")
        self.assertIsNotNone(result)
        self.assertTrue(any(ord(c) < 128 and c.isalpha() for c in result))

    def test_hurt_lang_fallback(self):
        """Unknown lang falls back to ja messages (or en — just must not crash)."""
        result = check_hurt_event(-8.0, lang="fr")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)


class RegisterFalsePositiveTests(unittest.TestCase):
    """Substring false-positives in register() — bugs fixed in _kw_match."""

    def test_whatever_does_not_trigger_hate(self):
        # "w-hate-ver" contains "hate" as substring; must NOT score negative
        m = MoodTracker()
        delta = m.register("whatever")
        self.assertEqual(delta, 0.0)
        self.assertEqual(m.affinity, AFFINITY_START)

    def test_dislike_does_not_trigger_like(self):
        # "dislike" contains "like"; only the explicit negative keyword fires
        m = MoodTracker()
        m.register("I dislike this")
        # affinity must decrease (dislike is negative); must NOT increase from "like"
        self.assertLess(m.affinity, AFFINITY_START)

    def test_dislike_you_does_not_trigger_like_you(self):
        # "like you" is a substring of "dislike you" — word boundary must block it
        m = MoodTracker()
        before = m.affinity
        m.register("I dislike you")
        # Only "dislike" (negative) fires; "like you" must NOT add positive hits
        self.assertLess(m.affinity, before)

    def test_unkind_does_not_trigger_kind(self):
        # "unkind" contains "kind"; must not yield a false positive boost
        m = MoodTracker()
        delta = m.register("that was unkind")
        self.assertLessEqual(delta, 0.0)

    def test_smugly_does_not_trigger_ugly(self):
        # "sm-ugly" — "ugly" is inside "smugly"; must not score negative
        m = MoodTracker()
        delta = m.register("she spoke smugly")
        self.assertEqual(delta, 0.0)

    def test_bakari_does_not_trigger_baka(self):
        # "ばかり" (grammar: only/nothing but) must NOT trigger the "馬鹿" check
        # The hiragana-only "ばか" entry was removed from defaults to prevent this.
        m = MoodTracker()
        delta = m.register("仕事ばかりで疲れた")
        self.assertEqual(delta, 0.0)

    def test_hate_still_matches(self):
        m = MoodTracker()
        delta = m.register("I hate you so much")
        self.assertLess(delta, 0)

    def test_like_still_matches(self):
        m = MoodTracker()
        delta = m.register("I like you")
        self.assertGreater(delta, 0)

    def test_kind_still_matches(self):
        m = MoodTracker()
        delta = m.register("you are so kind")
        self.assertGreater(delta, 0)

    def test_ugly_still_matches(self):
        m = MoodTracker()
        delta = m.register("that is so ugly")
        self.assertLess(delta, 0)

    def test_baka_kanji_still_matches(self):
        # "馬鹿" (kanji) must still fire as negative
        m = MoodTracker()
        delta = m.register("馬鹿にするな")
        self.assertLess(delta, 0)

    def test_nfc_input_matches_default_keywords(self):
        # Input NFC-normalized; Japanese keywords in source are also NFC — must match
        import unicodedata
        text = unicodedata.normalize("NFC", "ありがとう")
        m = MoodTracker()
        delta = m.register(text)
        self.assertGreater(delta, 0)


class FromDictNullValueTests(unittest.TestCase):
    """Regression: null JSON values in mood.json must use defaults instead of
    crashing with TypeError and silently resetting all user progress.

    dict.get(key, default) returns None (not default) when key is present with
    JSON null.  float(None) / int(None) raises TypeError which was previously
    caught only by MoodTracker.load()'s outer except — discarding all saved data.
    """

    def test_null_affinity_uses_default(self):
        data = {"affinity": None, "interactions": 5, "last_interaction_time": 0.0}
        m = MoodTracker.from_dict(data)
        self.assertAlmostEqual(m.affinity, float(AFFINITY_START), places=1)
        # Other non-null fields must survive
        self.assertEqual(m.interactions, 5)

    def test_null_interactions_uses_zero(self):
        data = {"affinity": 75.0, "interactions": None}
        m = MoodTracker.from_dict(data)
        self.assertEqual(m.interactions, 0)
        self.assertAlmostEqual(m.affinity, 75.0, places=1)

    def test_null_last_interaction_time_uses_zero(self):
        data = {"affinity": 80.0, "interactions": 10, "last_interaction_time": None}
        m = MoodTracker.from_dict(data)
        self.assertAlmostEqual(m._last_interaction_time, 0.0, places=3)

    def test_all_null_fields_use_defaults(self):
        """Every numeric field being null must not raise TypeError."""
        data = {
            "affinity": None,
            "interactions": None,
            "last_interaction_time": None,
            "first_interaction_time": None,
            "last_anniversary_days": None,
        }
        m = MoodTracker.from_dict(data)  # must not raise
        self.assertAlmostEqual(m.affinity, float(AFFINITY_START), places=1)
        self.assertEqual(m.interactions, 0)


class MoodTrackerThreadSafetyTests(unittest.TestCase):
    """Regression: register()/adjust()/decay() had no lock protecting
    affinity+interactions read-modify-write, so concurrent callers
    (autonomous behaviour thread + TTS handler) could lose updates."""

    def test_concurrent_register_no_lost_interactions(self):
        m = MoodTracker()
        n_threads, per_thread = 8, 500
        import threading as _threading
        barrier = _threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(per_thread):
                m.register("ありがとう")

        threads = [_threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(m.interactions, n_threads * per_thread)

    def test_concurrent_adjust_no_race(self):
        import threading as _threading
        m = MoodTracker(affinity=50.0)
        barrier = _threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(200):
                m.adjust(0.0)  # no-op but exercises the lock path

        threads = [_threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertAlmostEqual(m.affinity, 50.0, places=5)

    def test_concurrent_decay_does_not_corrupt_affinity(self):
        import threading as _threading
        m = MoodTracker(affinity=80.0, interactions=10,
                        last_interaction_time=__import__('time').time() - 3600)
        barrier = _threading.Barrier(4)

        def worker():
            barrier.wait()
            for _ in range(50):
                m.decay(1.0)

        threads = [_threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertGreaterEqual(m.affinity, 0.0)
        self.assertLessEqual(m.affinity, 100.0)

    def test_auto_decay_inline_no_reentrant_deadlock(self):
        """auto_decay() must not call decay() internally — both acquire _lock."""
        import time as _time
        m = MoodTracker(affinity=60.0, interactions=5,
                        last_interaction_time=_time.time() - 7200)
        delta = m.auto_decay()
        self.assertLessEqual(delta, 0.0)
        self.assertGreaterEqual(m.affinity, 0.0)


class DailyConversationGainCapTests(unittest.TestCase):
    """Socratic-method review found register() had a per-message cap
    (_MAX_DELTA_PER_MESSAGE) but no daily aggregate cap, so a user could send
    a handful of messages each containing 2-3 positive keywords and jump the
    whole affinity scale (0-100) in well under a minute — trivially bypassing
    the entire "relationship takes time" premise the mood system exists to
    enforce. Gifts already had a per-gift daily cooldown; conversation had
    nothing bounding total daily gain.

    _MAX_DAILY_CONVERSATION_GAIN caps only positive (delta > 0) gains per
    calendar day. Negative deltas (penalties for rude messages) and adjust()
    calls (gifts, milestones — which have their own guards) are unaffected.
    """

    def _spam_positive(self, tracker, n=10):
        deltas = []
        for _ in range(n):
            deltas.append(tracker.register("ありがとう、大好き、かわいい"))
        return deltas

    def test_repeated_positive_messages_are_capped_within_a_day(self):
        from mood import _MAX_DAILY_CONVERSATION_GAIN
        m = MoodTracker(affinity=0.0)
        deltas = self._spam_positive(m, n=10)
        self.assertLessEqual(
            sum(deltas), _MAX_DAILY_CONVERSATION_GAIN + 0.001,
            "Total same-day conversational gain must not exceed the daily cap, "
            "even from many messages that individually hit the per-message cap.",
        )

    def test_gain_stops_once_cap_reached(self):
        m = MoodTracker(affinity=0.0)
        self._spam_positive(m, n=10)
        affinity_at_cap = m.affinity
        # One more positive message the same "day" must add nothing further.
        extra = m.register("ありがとう、大好き")
        self.assertEqual(extra, 0.0)
        self.assertEqual(m.affinity, affinity_at_cap)

    def test_negative_messages_are_never_capped(self):
        """Penalties for rude messages must apply in full, even after the
        daily positive-gain cap has been reached — the cap only prevents
        farming positive affinity, it must not shield the user from
        legitimate negative consequences."""
        m = MoodTracker(affinity=50.0)
        self._spam_positive(m, n=10)  # exhaust the daily positive cap
        before = m.affinity
        delta = m.register("嫌い、うざい")
        self.assertLess(delta, 0.0)
        self.assertLess(m.affinity, before)

    def test_adjust_is_not_subject_to_the_conversation_cap(self):
        """adjust() backs gifts/milestones, which have their own anti-farming
        guards (e.g. gift_received_today); it must not additionally be
        throttled by the conversational daily cap."""
        m = MoodTracker(affinity=50.0)
        self._spam_positive(m, n=10)  # exhaust the daily positive cap
        before = m.affinity
        delta = m.adjust(5.0)
        self.assertEqual(delta, 5.0)
        self.assertGreater(m.affinity, before)

    def test_cap_resets_on_a_new_day(self):
        m = MoodTracker(affinity=0.0)
        self._spam_positive(m, n=10)
        self.assertEqual(m.register("ありがとう"), 0.0, "cap should be exhausted")
        # Simulate a day boundary by rewinding the tracked date directly,
        # mirroring how other tests inject last_login_date/gift_history state.
        m._daily_gain_date = "2000-01-01"
        delta = m.register("ありがとう、大好き、かわいい")
        self.assertGreater(delta, 0.0, "a new day must allow gains again")

    def test_daily_gain_state_round_trips_through_dict(self):
        m = MoodTracker(affinity=0.0)
        self._spam_positive(m, n=10)
        data = m.to_dict()
        self.assertIn("daily_gain_date", data)
        self.assertIn("daily_gain_total", data)
        restored = MoodTracker.from_dict(data)
        self.assertEqual(restored._daily_gain_date, m._daily_gain_date)
        self.assertAlmostEqual(restored._daily_gain_total, m._daily_gain_total)
        # The cap must still hold after a save/load round trip (no reset
        # exploit via restarting the app).
        self.assertEqual(restored.register("ありがとう、大好き"), 0.0)

    def test_single_message_still_respects_per_message_cap_under_daily_cap(self):
        """Sanity: with plenty of daily headroom, the existing per-message
        cap (_MAX_DELTA_PER_MESSAGE) still applies unchanged."""
        from mood import _MAX_DELTA_PER_MESSAGE
        m = MoodTracker(affinity=0.0)
        delta = m.register("ありがとう、大好き、かわいい、うれしい、すごい")
        self.assertLessEqual(delta, _MAX_DELTA_PER_MESSAGE + 0.001)


class NegationAndEmojiSentimentTests(unittest.TestCase):
    """Hybrid sentiment (research A2): classify_sentiment / register must
    account for negation and emoji, not just naive keyword presence.
    Previously '好きじゃない' / 'I don't like you' scored POSITIVE because the
    positive keyword was a substring of the negated phrase."""

    def _cs(self, text):
        from mood import classify_sentiment
        return classify_sentiment(text)

    # --- negated positive -> negative ---
    def test_ja_suki_janai_is_negative(self):
        self.assertEqual(self._cs("好きじゃない"), -1)

    def test_ja_daisuki_dewanai_is_negative(self):
        self.assertEqual(self._cs("大好きではない"), -1)

    def test_en_dont_like_is_negative(self):
        self.assertEqual(self._cs("I don't like you"), -1)

    def test_en_not_love_is_negative(self):
        self.assertEqual(self._cs("I do not love this"), -1)

    # --- negated negative -> cancelled (neutral) ---
    def test_ja_kirai_janai_is_neutral(self):
        self.assertEqual(self._cs("嫌いじゃない"), 0)

    def test_en_not_annoying_is_neutral(self):
        self.assertEqual(self._cs("that is not annoying"), 0)

    # --- un-negated cases unchanged ---
    def test_plain_positive_unchanged(self):
        self.assertEqual(self._cs("大好き"), 1)

    def test_plain_negative_unchanged(self):
        self.assertEqual(self._cs("最悪、むかつく"), -1)

    # --- emoji / kaomoji carry sentiment ---
    def test_positive_emoji_is_positive(self):
        self.assertEqual(self._cs("今日はいい天気😊"), 1)

    def test_negative_emoji_is_negative(self):
        self.assertEqual(self._cs("そうなんだ😢"), -1)

    def test_positive_kaomoji_is_positive(self):
        self.assertEqual(self._cs("やったね (^^)"), 1)

    # --- register() agrees with classify_sentiment on negation ---
    def test_register_negated_positive_decreases_affinity(self):
        m = MoodTracker()
        before = m.affinity
        m.register("好きじゃない")
        self.assertLess(m.affinity, before)

    def test_register_negated_negative_does_not_decrease(self):
        m = MoodTracker()
        before = m.affinity
        m.register("嫌いじゃない")
        # "not dislike" is cancelled — affinity must not drop.
        self.assertGreaterEqual(m.affinity, before)


if __name__ == "__main__":
    unittest.main()


class EarnSharesTheDailyBudgetTests(unittest.TestCase):
    """稼げる上昇（会話・プレゼント）が同じ日次予算を共有すること。

    共有しないと `max_daily_gain` は成長弧の長さを決めない。実際、
    プレゼントは `adjust()` を直接呼んで上限を完全に迂回しており、
    上限を 5.0/日（最短 6 日の弧）にしても **7 種を配るだけで初日に最高
    レベルへ到達できた**（ギフト合計 30.5 = 開始 50.0 から close の閾値
    80.0 までちょうど届く）。
    """

    def test_gift_sized_bonuses_cannot_outrun_the_daily_cap(self):
        """全ギフトぶん（合計 30.5）を earn しても上限までしか入らない。"""
        t = MoodTracker()
        applied = sum(t.earn(b) for b in (5.0, 4.0, 3.5, 4.0, 5.0, 3.0, 6.0))
        self.assertAlmostEqual(applied, t.max_daily_gain, places=6)
        self.assertEqual(t.level, "neutral", "初日に最高レベルへ到達している")

    def test_earn_returns_what_was_actually_applied(self):
        """表示を実態に合わせられるよう、反映量を返すこと。"""
        t = MoodTracker(max_daily_gain=3.0)
        self.assertAlmostEqual(t.earn(5.0), 3.0, places=6)
        self.assertAlmostEqual(t.earn(5.0), 0.0, places=6)

    def test_conversation_and_gifts_draw_from_one_budget(self):
        """会話で使い切ったらプレゼントでは伸びない（逆も同じ）。"""
        t = MoodTracker()
        for _ in range(10):
            t.register("ありがとう")
        spent = t.affinity
        self.assertAlmostEqual(t.earn(6.0), 0.0, places=6)
        self.assertAlmostEqual(t.affinity, spent, places=6)

    def test_earn_does_not_dilute_penalties(self):
        """減少は上限の対象外（正当なマイナスを薄めない）。"""
        t = MoodTracker()
        for _ in range(10):
            t.register("ありがとう")   # 予算を使い切る
        before = t.affinity
        self.assertLess(t.earn(-4.0), 0.0)
        self.assertLess(t.affinity, before)

    def test_adjust_stays_uncapped_for_one_off_events(self):
        """誕生日・記念日など繰り返せないボーナスは従来どおり満額。"""
        t = MoodTracker()
        for _ in range(10):
            t.register("ありがとう")
        before = t.affinity
        t.adjust(8.0)
        self.assertAlmostEqual(t.affinity, before + 8.0, places=6)

    def test_login_bonus_consumes_the_daily_budget(self):
        """デイリーログインボーナスは毎日積む上昇なので、同じ予算を使うこと。

        adjust() で上乗せしていた頃は、会話の上限いっぱい + ログイン 2.0〜5.0
        で 1 日 7〜10 点稼げ、「最短 6 日」の弧が実際には 4 日目に close に
        達していた（実測）。
        """
        from mood import check_daily_login
        t = MoodTracker()
        check_daily_login(t, lang="ja")
        for _ in range(20):
            t.register("ありがとう")
        self.assertAlmostEqual(t.affinity, 50.0 + t.max_daily_gain, places=6,
                               msg="ログインボーナスが日次予算の外で上乗せされている")

    def test_the_arc_takes_six_days_with_login_bonuses_included(self):
        """実際の 1 日（ログイン → 会話）を 6 日回して、5 日目まで close に達しないこと。

        register() だけを回す既存の弧テストは、ログインボーナスの迂回を
        捕まえられなかった。実経路で数える。
        """
        import datetime
        from mood import check_daily_login
        t = MoodTracker()
        start = datetime.date(2026, 1, 1)
        for day in range(1, 7):
            today = (start + datetime.timedelta(days=day - 1)).isoformat()
            t._daily_gain_date = None  # 日付が変わったものとして予算をリセット
            check_daily_login(t, lang="ja", today=today)
            for _ in range(20):
                t.register("ありがとう")
            if day < 6:
                self.assertNotEqual(t.level, "close", f"day {day} で最高レベルに達している")
        self.assertEqual(t.level, "close")


class DailyGainCapConfigTests(unittest.TestCase):
    """会話由来の日次上昇上限が設定可能であること。

    この値が関係の成長弧の長さを決める。開始 50.0 から close の閾値 80.0 まで
    は 30.0。かつての既定 30.0/日では**初日の 8 メッセージほどで最高レベルに
    到達し、「セッションを跨いで育つ関係」は 1 セッションで終わっていた**。
    製品オーナーの判断で 5.0（最短 6 日の弧）へ変更した。

    config/mood_config.json から上書きできるので、速い弧が欲しい人は
    コードを編集せずに戻せる。
    """

    def test_default_is_a_multi_day_arc(self):
        """既定は 5.0 = 最短 6 日の弧（オーナー判断で 30.0 から変更）。"""
        self.assertEqual(MoodTracker().max_daily_gain, 5.0)
        self.assertEqual(mood._MAX_DAILY_CONVERSATION_GAIN, 5.0)

    def test_default_does_not_reach_the_top_level_on_day_one(self):
        """1 日どれだけ話しても最高レベルには届かないこと。

        これが変更の要点である — 好感度で釣って初日に関係を終わらせない。
        """
        t = MoodTracker()
        for _ in range(30):
            t.register("ありがとう")
        self.assertLess(t.affinity, 60.0)
        self.assertEqual(t.level, "neutral")

    def test_the_arc_takes_at_least_six_days(self):
        """日次上限いっぱい稼いでも close まで 6 日かかること（30.0 / 5.0）。"""
        t = MoodTracker()
        for day in range(1, 7):
            t._daily_gain_date = None  # 日付が変わったものとして上限をリセット
            for _ in range(20):
                t.register("ありがとう")
            if day < 6:
                self.assertNotEqual(t.level, "close",
                                    f"day {day} で最高レベルに達している")
        self.assertEqual(t.level, "close")

    def test_a_higher_cap_shortens_the_arc(self):
        """上げれば従来どおり初日に到達できる（設定で戻せる）。"""
        t = MoodTracker(max_daily_gain=30.0)
        for _ in range(30):
            t.register("ありがとう")
        self.assertEqual(t.level, "close")

    def test_cap_is_read_from_mood_config(self):
        kwargs = mood._kwargs_from_mood_config({"max_daily_gain": 7.5})
        self.assertEqual(kwargs["max_daily_gain"], 7.5)

    def test_non_numeric_cap_in_config_is_ignored(self):
        for bad in ("lots", None, [], {}):
            with self.subTest(value=bad):
                self.assertNotIn("max_daily_gain",
                                 mood._kwargs_from_mood_config({"max_daily_gain": bad}))

    def test_negative_cap_means_no_conversational_gain(self):
        """負値は「上限なし」ではなく 0 と解釈すること。"""
        t = MoodTracker(max_daily_gain=-5.0)
        before = t.affinity
        t.register("ありがとう")
        self.assertEqual(t.affinity, before)

    def test_penalties_ignore_the_cap(self):
        """上限は「稼ぎすぎ」だけを防ぎ、正当なマイナス影響は薄めないこと。"""
        t = MoodTracker(max_daily_gain=0.0)
        before = t.affinity
        t.register("嫌い")
        self.assertLess(t.affinity, before)


class ConfessionMinimumRelationshipTests(unittest.TestCase):
    """告白には「実体のある関係」を要求すること（love-bombing 防止）。

    以前は friendly→close の遷移が起きた瞬間に告白していた。既定の好感度設定
    では**新規ユーザーが「大好き」と 3 回打つだけで**
    「こんなに誰かのことを好きになったの、初めてかもしれない。…あなたの
    ことだよ。」に到達した。出会って 3 メッセージの相手に永続的な愛着を
    宣言するのは love-bombing であり、本リポジトリが別れぎわ
    （farewell_integrity）・不在の非難（挨拶）・依存（usage_guardrails）に
    ついて既に禁じているものと同じ型の操作である。

    ロマンス要素そのものは製品の設計判断として尊重する。ここで守るのは
    「関係が無いところに関係の告白を置かない」という一点だけである。
    """

    def _fresh(self, **kw):
        # ここで見たいのは「好感度は最高でも、日数・対話数が足りなければ
        # 告白しない」こと。好感度を 1 日で最高まで上げる必要があるので、
        # 成長弧の日次上限（既定 5.0）だけ外す（上限自体は別テストの担当）。
        kw.setdefault("max_daily_gain", 1000.0)
        return MoodTracker(**kw)

    def test_a_brand_new_user_cannot_trigger_a_confession(self):
        t = self._fresh()
        for _ in range(40):
            before = t.affinity
            t.register("大好き")
            self.assertIsNone(
                check_confession_event(t, before, t.affinity, lang="ja"),
                f"新規ユーザーが {t.interactions} メッセージで告白を受けた")
        self.assertEqual(t.level, "close", "前提: 好感度自体は close に達している")

    def test_confession_fires_once_the_relationship_is_real(self):
        t = self._fresh(affinity=81.0, interactions=50,
                        first_interaction_time=time.time() - 30 * 86400)
        self.assertIsNotNone(check_confession_event(t, 79.0, 81.0, lang="ja"))

    def test_interaction_count_alone_is_not_enough(self):
        """回数だけ稼いでも、経過日数が足りなければ告白しない。"""
        t = self._fresh(affinity=81.0, interactions=500,
                        first_interaction_time=time.time() - 3600)
        self.assertIsNone(check_confession_event(t, 79.0, 81.0, lang="ja"))

    def test_elapsed_days_alone_is_not_enough(self):
        """日数が経っていても、ほとんど会話していなければ告白しない。"""
        t = self._fresh(affinity=81.0, interactions=2,
                        first_interaction_time=time.time() - 365 * 86400)
        self.assertIsNone(check_confession_event(t, 79.0, 81.0, lang="ja"))

    def test_no_first_interaction_time_means_no_relationship(self):
        t = self._fresh(affinity=81.0, interactions=100,
                        first_interaction_time=0.0)
        self.assertIsNone(check_confession_event(t, 79.0, 81.0, lang="ja"))

    def test_deferred_confession_is_not_lost(self):
        """条件未達で見送った告白が、条件成立後に発火すること。

        判定を「friendly→close の遷移」に置いたままだと、遷移は二度と起きない
        ので告白が永久に失われる。close に留まっているあいだ評価し続ける。
        """
        t = self._fresh()
        for _ in range(40):
            before = t.affinity
            t.register("大好き")
            check_confession_event(t, before, t.affinity, lang="ja")
        self.assertFalse(t._confession_done, "見送りで done を立ててはいけない")
        # 関係が実体を持つ日が来たら発火する
        t._first_interaction_time = time.time() - 30 * 86400
        before = t.affinity
        t.register("大好き")
        self.assertIsNotNone(check_confession_event(t, before, t.affinity, lang="ja"))

    def test_thresholds_are_configurable(self):
        kwargs = mood._kwargs_from_mood_config(
            {"confession_min_days": 0, "confession_min_interactions": 0})
        self.assertEqual(kwargs["confession_min_days"], 0.0)
        self.assertEqual(kwargs["confession_min_interactions"], 0)

    def test_zero_thresholds_restore_the_old_immediate_behaviour(self):
        """0 に設定すれば従来どおり即座に発火すること（後方互換の逃げ道）。"""
        t = self._fresh(affinity=81.0, confession_min_days=0,
                        confession_min_interactions=0)
        self.assertIsNotNone(check_confession_event(t, 79.0, 81.0, lang="ja"))

    def test_defaults_match_the_first_anniversary_milestone(self):
        """既定の日数が、製品自身の「しばらく一緒にいた」の定義と揃っていること。"""
        self.assertEqual(mood._CONFESSION_MIN_DAYS, 7.0)
        self.assertIn(7, mood._ANNIVERSARY_MILESTONES)

