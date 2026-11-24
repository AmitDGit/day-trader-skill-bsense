"""The Time Machine on generated NSE sessions (seeded random walks in Kite's candle
shape), so the replay math is tested on the NSE clock: 75 bars, 9:15 to 15:30 IST."""

import contextlib
import datetime
import io
import json
import os
import random
import shutil
import tempfile
import unittest

from _load import FIX, load

tm = load("trader-timemachine", "timemachine")
PLAN_DAY = datetime.date(2026, 11, 23)


def trading_days_before(day, n):
    """n NSE trading days before `day`, oldest first (weekends and NSE holidays skipped)."""
    hol = load("trader-alerts", "alerts").NSE_HOLIDAYS
    out, d = [], day - datetime.timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in hol:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return list(reversed(out))


def session(day, price, rng, bars=75):
    rows = []
    t = datetime.datetime.combine(day, datetime.time(9, 15))
    for _ in range(bars):
        o = price
        c = round(o * (1 + rng.gauss(0, 0.002)), 1)
        h = round(max(o, c) * (1 + abs(rng.gauss(0, 0.001))), 1)
        lo = round(min(o, c) * (1 - abs(rng.gauss(0, 0.001))), 1)
        rows.append({"date": t.strftime("%Y-%m-%dT%H:%M:%S+05:30"), "open": o, "high": h, "low": lo, "close": c,
                     "volume": rng.randint(1000, 9000)})
        price = c
        t += datetime.timedelta(minutes=5)
    return rows, price


def kite_file(path, n_days=25, short_day=None, seed=3):
    rng = random.Random(seed)
    rows, price = [], 1000.0
    for d in trading_days_before(PLAN_DAY, n_days):
        r, price = session(d, price, rng, bars=40 if d == short_day else 75)
        rows += r
    today, _ = session(PLAN_DAY, price, rng, bars=24)        # the plan's day, up to 11:15
    rows += today
    with open(path, "w") as fh:
        json.dump({"data": rows}, fh)
    return today


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


class TimeMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "DEMO-5minute.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def plan_args(self, today, k=12, extra=()):
        entry = today[k - 1]["close"]
        return ["run", "--symbol", "DEMO", "--date", PLAN_DAY.isoformat(), "--entry", str(entry),
                "--stop", "%.1f" % (entry * 0.995), "--target", "%.1f" % (entry * 1.01),
                "--entry-time", "10:15 AM", "--setup", "level", "--offline", self.file,
                "--now", "2026-11-23 11:20", "--json", "--replays", "2000"] + list(extra)

    def test_kite_candles_replay_and_repeat(self):
        today = kite_file(self.file)
        code, out, err = run(self.plan_args(today))
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        mc = doc["mc"]
        self.assertEqual(mc["replays"], 2000)
        self.assertAlmostEqual(mc["p_target"] + mc["p_stop"] + mc["p_neither"], 1.0, places=2)
        self.assertEqual(mc["pool_sessions"], 25)
        self.assertEqual(mc["bars_left"], 63)                             # 75 bars, the entry closed the 12th
        self.assertEqual(doc["data"]["symbol"], "DEMO.NS")
        code2, out2, _ = run(self.plan_args(today))
        self.assertEqual(json.loads(out2)["mc"], mc)                       # same seed, same numbers
        code3, out3, _ = run(self.plan_args(today, extra=["--seed", "7"]))
        self.assertNotEqual(json.loads(out3)["mc"], mc)

    def test_a_short_session_is_left_out(self):
        days = trading_days_before(PLAN_DAY, 25)
        today = kite_file(self.file, short_day=days[5])
        code, out, err = run(self.plan_args(today))
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["mc"]["pool_sessions"], 24)
        self.assertEqual(doc["data"]["short_sessions_left_out"], [{"date": days[5].isoformat(), "bars": 40}])

    def test_fewer_than_20_sessions_is_refused(self):
        today = kite_file(self.file, n_days=15)
        code, _, err = run(self.plan_args(today))
        self.assertEqual(code, 1)
        self.assertIn("20", err)

    def test_until_flat_by(self):
        today = kite_file(self.file)
        code, out, err = run(self.plan_args(today, extra=["--until", "15:10"]))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["mc"]["until"], "15:10")

    def test_the_data_must_be_the_plans_symbol(self):
        kite_file(self.file)
        bad = os.path.join(self.tmp, "x.json")
        with open(self.file) as fh:
            doc = json.load(fh)
        doc["symbol"] = "OTHER"
        with open(bad, "w") as fh:
            json.dump(doc, fh)
        args = self.plan_args([{"close": 1000.0}] * 12)
        args[args.index(self.file)] = bad
        code, _, err = run(args)
        self.assertEqual(code, 1)
        self.assertIn("the data is for OTHER.NS but the plan is for DEMO", err)


if __name__ == "__main__":
    unittest.main()
