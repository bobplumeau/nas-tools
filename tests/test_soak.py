import unittest

from datetime import datetime, timedelta

from nas_t.soak import SoakDetector, rise_per_window

T0 = datetime(2026, 1, 1, 12, 0, 0)


def ramp(minutes, start_temp, per_min, step_sec=15):
    n = int(minutes * 60 / step_sec)
    return [(T0 + timedelta(seconds=i * step_sec), start_temp + per_min * i * step_sec / 60) for i in range(n + 1)]


class TestRisePerWindow(unittest.TestCase):
    def test_linear_ramp(self):
        self.assertAlmostEqual(rise_per_window(ramp(10, 50, 0.2), 10), 2.0, places=6)

    def test_flat(self):
        self.assertAlmostEqual(rise_per_window(ramp(10, 60, 0.0), 10), 0.0)

    def test_too_few_points(self):
        self.assertIsNone(rise_per_window([(T0, 50.0)], 10))

    def test_quantised_noise_on_flat_line_stays_small(self):
        pts = [(T0 + timedelta(seconds=15 * i), 62.0 + (i % 2)) for i in range(41)]
        self.assertLess(abs(rise_per_window(pts, 10)), 0.1)


class TestSoakDetector(unittest.TestCase):
    def test_not_before_min_load(self):
        d = SoakDetector(T0, min_load_min=20)
        pts = ramp(15, 60, 0.0)
        self.assertFalse(d.check(pts, pts[-1][0]))
        self.assertEqual(d.hits, 0)

    def test_needs_consecutive_confirmations(self):
        d = SoakDetector(T0, min_load_min=20, confirm=2)
        pts = ramp(30, 60, 0.0)
        self.assertFalse(d.check(pts[:-4], pts[-5][0]))
        self.assertTrue(d.check(pts, pts[-1][0]))

    def test_still_rising_resets_hits(self):
        d = SoakDetector(T0, min_load_min=20, max_rise=0.5)
        rising = ramp(30, 50, 0.2)
        self.assertFalse(d.check(rising, rising[-1][0]))
        self.assertFalse(d.check(rising, rising[-1][0]))
        self.assertEqual(d.hits, 0)
        self.assertAlmostEqual(d.last_rise, 2.0, places=3)

    def test_ignores_samples_before_load_start(self):
        load_start = T0 + timedelta(minutes=25)
        pts = ramp(10, 30, 3.0) + [(T0 + timedelta(minutes=25, seconds=15 * i), 60.0) for i in range(200)]
        d = SoakDetector(load_start, min_load_min=0, window_min=60, confirm=1)
        self.assertTrue(d.check(pts, pts[-1][0]))


if __name__ == "__main__":
    unittest.main()
