import tempfile
import unittest

from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from nas_t.plotting import compare_runs, plot_run, smooth, steady_state  # noqa: E402
from nas_t.runs import append_event, event_time, read_events, read_samples, series, write_events  # noqa: E402

T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_run(root: Path, name: str, label: str, core_rise: float) -> Path:
    """5 min idle, 20 min load where coretemp rises then plateaus, system flat."""
    run = root / name
    run.mkdir()
    load_start, load_stop = T0 + timedelta(minutes=5), T0 + timedelta(minutes=25)
    write_events(run, {"label": label, "log_start": T0, "load_start": load_start, "load_stop": load_stop})
    lines = ["timestamp,sensor,temperature_c,healthy"]
    for i in range(0, 30 * 4):
        t = T0 + timedelta(seconds=15 * i)
        loaded = load_start <= t <= load_stop
        core = 40.0 + (core_rise if loaded and t > load_start + timedelta(minutes=3) else 0.0)
        ts = t.isoformat(timespec="seconds")
        lines += [f"{ts},disk1,40.0,True", f"{ts},coretemp,{core},", f"{ts},cpu,{core - 5},", f"{ts},system,36.0,",
                  f"{ts},eth0,None,"]
    (run / "smart_log.csv").write_text("\n".join(lines) + "\n")
    return run


class TestRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_events_roundtrip_and_later_entries_win(self):
        run = make_run(self.root, "a", "1 layer", 20)
        append_event(run, "load_stop", T0 + timedelta(minutes=15))
        events = read_events(run)
        self.assertEqual(events["label"], "1 layer")
        self.assertEqual(event_time(events, "load_stop"), T0 + timedelta(minutes=15))

    def test_samples_pivot_and_skip_missing(self):
        samples = read_samples(make_run(self.root, "a", "x", 20))
        self.assertEqual(len(samples), 120)
        self.assertNotIn("eth0", samples[0][1])
        diff = series(samples, "coretemp", minus="system")
        self.assertEqual(diff[0][1], 4.0)

    def test_steady_state_uses_end_of_load(self):
        run = make_run(self.root, "a", "x", 20)
        value = steady_state(read_samples(run), read_events(run))
        self.assertAlmostEqual(value, 24.0)


class TestPlotting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_smooth_keeps_ends_level(self):
        out = smooth([50.0] * 40, sigma=3)
        self.assertAlmostEqual(out[0], 50.0)
        self.assertAlmostEqual(out[-1], 50.0)
        self.assertEqual(len(out), 40)

    def test_plot_run_saves_png(self):
        run = make_run(self.root, "a", "x", 20)
        out = plot_run(run, sigma=2, show=False)
        self.assertTrue(out.exists())

    def test_plot_run_before_any_data(self):
        run = self.root / "empty"
        run.mkdir()
        self.assertTrue(plot_run(run, show=False).exists())

    def test_compare_reports_difference(self):
        a = make_run(self.root, "a", "1 layer", 24)
        b = make_run(self.root, "b", "2 layers", 20)
        out, results = compare_runs([a, b], out=self.root / "cmp.png", show=False)
        self.assertTrue(out.exists())
        self.assertEqual([r[0] for r in results], ["1 layer", "2 layers"])
        self.assertAlmostEqual(results[0][2] - results[1][2], 4.0)


if __name__ == "__main__":
    unittest.main()
