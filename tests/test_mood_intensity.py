"""
Unit tests for the emotion-intensity-weighted lexicon (research A3).

Before A3 every sentiment word contributed a flat ±1 count, so "大好き" moved
affinity exactly as much as "好き" and "最悪" as much as "つまらない".  A3 gives
each word a weak/medium/strong intensity weight so the magnitude of the
affinity change reflects how strong the wording is — while keeping the polarity
sign (classify_sentiment) and the "1 word = 1 count" semantics unchanged, and
leaving unlisted / custom words at weight 1.0.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from mood import (  # noqa: E402
    MoodTracker,
    AFFINITY_START,
    classify_sentiment,
    _intensity_of,
    _polarity_weights,
    _polarity_counts,
    _DEFAULT_INTENSITY,
)


def _delta(text: str) -> float:
    return MoodTracker(affinity=50.0).register(text)


class IntensityLookupTests(unittest.TestCase):
    def test_strong_positive_weight_above_one(self):
        self.assertGreater(_intensity_of("大好き"), 1.0)
        self.assertGreater(_intensity_of("love"), 1.0)

    def test_weak_negative_weight_below_one(self):
        self.assertLess(_intensity_of("つまらない"), 1.0)
        self.assertLess(_intensity_of("boring"), 1.0)

    def test_unlisted_word_defaults_to_one(self):
        self.assertEqual(_intensity_of("好き"), _DEFAULT_INTENSITY)
        self.assertEqual(_intensity_of("yay"), _DEFAULT_INTENSITY)
        self.assertEqual(_intensity_of("完全に未知の語"), _DEFAULT_INTENSITY)

    def test_lookup_is_nfc_and_case_insensitive(self):
        self.assertEqual(_intensity_of("LOVE"), _intensity_of("love"))


class IntensityScoringTests(unittest.TestCase):
    def test_strong_positive_moves_more_than_mild(self):
        # 「好き」(1.0) より「大好き」(強) の方が好感度が大きく動く。
        self.assertGreater(_delta("大好き"), _delta("好き"))

    def test_strong_negative_moves_more_than_mild(self):
        # 「つまらない」(弱) より「最悪」(強) の方が大きく下げる。
        self.assertLess(_delta("最悪"), _delta("つまらない"))

    def test_weak_negative_less_than_default_negative(self):
        # 弱い否定語は既定係数(6.0)未満の幅にとどまる。
        self.assertGreater(_delta("つまらない"), -6.0)
        self.assertLess(_delta("つまらない"), 0.0)

    def test_unlisted_positive_uses_plain_delta(self):
        # 強度未指定の語は係数そのまま（既存挙動を保つ）。
        # max_daily_gain は既定 5.0 なので、ここでは delta 自体を見るために
        # 上限を外す（上限の検証は test_mood.py の DailyGainCap 側の担当）。
        m = MoodTracker(affinity=50.0, positive={"en": ["yay"]}, positive_delta=7.0,
                        max_daily_gain=100.0)
        self.assertAlmostEqual(m.register("yay"), 7.0, places=5)

    def test_unlisted_negative_uses_plain_delta(self):
        m = MoodTracker(affinity=50.0, negative={"en": ["ugh"]}, negative_delta=9.0)
        self.assertAlmostEqual(m.register("ugh"), -9.0, places=5)


class IntensityPreservesPolarityTests(unittest.TestCase):
    """Intensity must change magnitude only — never the +1/-1/0 sign."""

    def test_classify_sign_unchanged_for_strong_positive(self):
        self.assertEqual(classify_sentiment("大好き"), 1)

    def test_classify_sign_unchanged_for_strong_negative(self):
        self.assertEqual(classify_sentiment("最悪"), -1)

    def test_classify_neutral_stays_neutral(self):
        self.assertEqual(classify_sentiment("今日は水曜日です"), 0)

    def test_polarity_counts_stay_integer_and_flat(self):
        # 強度に関係なく、カウントは 1 語 = 1（整数）。
        pos, neg = _polarity_counts("最悪", [], ["最悪"])
        self.assertEqual((pos, neg), (0, 1))
        self.assertIsInstance(pos, int)
        self.assertIsInstance(neg, int)


class IntensityWeightsSumTests(unittest.TestCase):
    def test_weights_are_float_and_intensity_scaled(self):
        pos, neg = _polarity_weights("つまらない", [], ["つまらない"])
        self.assertEqual(pos, 0.0)
        self.assertAlmostEqual(neg, _intensity_of("つまらない"), places=5)
        self.assertIsInstance(neg, float)

    def test_negated_positive_keeps_its_intensity_as_negative(self):
        # 「大好きじゃない」= 強い肯定語が否定 → 否定側にその強度で計上。
        pos, neg = _polarity_weights("大好きじゃない", ["大好き"], [])
        self.assertEqual(pos, 0.0)
        self.assertGreater(neg, 1.0)


class IntensityRegressionSanityTests(unittest.TestCase):
    def test_positive_still_increases(self):
        self.assertGreater(_delta("ありがとう"), 0)

    def test_negative_still_decreases(self):
        self.assertLess(_delta("きらい"), 0)

    def test_per_message_cap_still_holds(self):
        m = MoodTracker(affinity=50.0)
        m.register("大好き 最高 かわいい うれしい すごい 感謝 やさしい 大好き")
        self.assertLessEqual(m.affinity - 50.0, 10.0)


if __name__ == "__main__":
    unittest.main()
