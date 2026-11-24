import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, load

scan = load("trader-scanner", "scan")
KITE = os.path.join(FIX, "kite")
CSV = os.path.join(FIX, "nifty", "ind_nifty100list.csv")
EPOCH = datetime.datetime(1970, 1, 1)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


def ts(ist):
    """'2026-11-23 09:15' IST -> Unix seconds."""
    local = datetime.datetime.strptime(ist, "%Y-%m-%d %H:%M")
    return int((local - datetime.timedelta(hours=5, minutes=30) - EPOCH).total_seconds())


def daily_series(closes, last_day="2026-11-23"):
    """Daily closes on consecutive NSE trading days ending last_day (holidays skipped)."""
    days, d = [], datetime.date.fromisoformat(last_day)
    while len(days) < len(closes):
        if scan.trading_day(d)[0]:
            days.append(d)
        d -= datetime.timedelta(days=1)
    days.reverse()
    t = [ts("%s 09:15" % x.isoformat()) for x in days]
    return {"t": t, "c": list(closes), "o": None, "h": None, "l": None, "v": None,
            "meta": {"regularMarketPrice": closes[-1], "regularMarketVolume": 2000000}}


class Universe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "universe.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_the_index_csv(self):
        with open(CSV, encoding="utf-8") as fh:
            rows = scan.parse_index_csv(fh.read())
        syms = [r[0] for r in rows]
        self.assertEqual(len(rows), 10)                         # the E1 (partly paid) row is dropped
        self.assertIn("M&M", syms)
        self.assertIn("BAJAJ-AUTO", syms)
        self.assertNotIn("EXAMPLEPP", syms)
        with self.assertRaises(scan.ScanError):
            scan.parse_index_csv("Symbol;Name\nX;Y\n")

    def test_universe_from_the_csv_plus_holdings_and_extras(self):
        hold = os.path.join(self.tmp, "kite-holdings.json")
        with open(hold, "w") as fh:
            json.dump({"data": [{"tradingsymbol": "IRCTC", "exchange": "NSE"},
                                {"tradingsymbol": "RELIANCE", "exchange": "NSE"},
                                {"tradingsymbol": "SGBJUN31", "exchange": "BSE"}]}, fh)
        code, out, err = run(["universe", "--offline", os.path.dirname(CSV), "--holdings", hold,
                              "--add", "zomato,TCS", "--out", self.out])
        self.assertEqual(code, 0, err)
        self.assertIn("Nifty 100 constituents", out)
        self.assertIn("Added 2 more: IRCTC, ZOMATO.", out)
        with open(self.out) as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 12)
        self.assertIn("IRCTC|from your Kite holdings", lines)
        self.assertEqual(scan.symbols_from_file(self.out)[0], "BAJAJ-AUTO")

    def test_an_unknown_index_is_refused(self):
        code, _, err = run(["universe", "--index", "sensex", "--offline", CSV, "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("--index wants one of", err)


class Orb(unittest.TestCase):
    def test_offline_kite_files_by_their_saved_names(self):
        data, failed = scan.load_offline(KITE)
        self.assertEqual(sorted(data), ["RELIANCE", "TITAN"])     # kite-quotes.json is not a chart
        self.assertEqual(failed, {})
        self.assertEqual(scan._stem("BAJAJ-AUTO-2026-11-23-5minute.json"), "BAJAJ-AUTO")
        self.assertEqual(scan._stem("TITAN.NS.json"), "TITAN")

    def test_titan_and_reliance_at_10_00_no_breakout(self):
        # TITAN's 9:15 to 9:30 range: high 4678.10 (the 9:20 bar); RELIANCE's 1390.00.
        # Neither closed above by 10:00 on 23 November 2026.
        code, out, err = run(["orb", "--offline", KITE, "--now", "2026-11-23 10:00", "--no-write",
                              "--min-price", "0"])
        self.assertEqual(code, 1, err)
        self.assertIn("Opening-range breakout scan, Mon 2026-11-23 10:00 AM IST: 15-minute range (9:15 to 9:30 AM)",
                      out)
        self.assertIn("No chart closed above its opening-range high by 10:00 AM.", out)

    def test_titan_breaks_out_at_the_end_of_the_day(self):
        # the 15:05 bar closed 4682.00 over the 4678.10 range high; scan with no entry cutoff
        code, out, err = run(["orb", "--offline", KITE, "--symbols", "TITAN", "--now", "2026-11-23 15:12",
                              "--until", "15:30", "--no-write", "--min-price", "0", "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        hit = doc["hits"][0]
        self.assertEqual((hit["symbol"], hit["or_high"], hit["price"], hit["at"]),
                         ("TITAN", 4678.1, 4682.0, "3:10 PM"))

    def test_the_cutoff_is_the_entry_window(self):
        code, out, err = run(["orb", "--offline", KITE, "--symbols", "TITAN", "--now", "2026-11-23 15:12",
                              "--no-write", "--min-price", "0"])
        self.assertEqual(code, 1, out + err)                      # default --until 14:45: too late to count

    def test_before_the_range_is_set(self):
        code, _, err = run(["orb", "--offline", KITE, "--now", "2026-11-23 09:25", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("the 15-minute opening range runs 9:15 to", err)


class Daily(unittest.TestCase):
    def test_breakout_and_oversold(self):
        up = [100.0 + 0.1 * i for i in range(40)] + [110.0]
        down = [200.0 - 2.0 * i for i in range(40)]
        data = {"UPCO": daily_series(up), "DOWNCO": daily_series(down)}
        now = scan.parse_now("2026-11-24 08:30")             # a holiday morning: Monday is the last close
        hits, counts, last = scan.scan_daily(data, ["UPCO", "DOWNCO"], now, 50.0, 100000)
        tags = {h["symbol"]: h["setups"] for h in hits}
        self.assertIn("breakout_20d", tags["UPCO"])
        self.assertIn("oversold", tags["DOWNCO"])
        self.assertEqual(last.isoformat(), "2026-11-23")

    def test_the_price_floor_is_in_rupees(self):
        cheap = daily_series([20.0 + 0.01 * i for i in range(40)])
        hits, counts, _ = scan.scan_daily({"PENNY": cheap}, ["PENNY"], scan.parse_now("2026-11-24 08:30"),
                                          50.0, 0)
        self.assertEqual((hits, counts["illiquid"]), ([], 1))


if __name__ == "__main__":
    unittest.main()
