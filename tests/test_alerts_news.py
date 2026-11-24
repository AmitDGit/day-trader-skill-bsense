import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, load

alerts = load("trader-alerts", "alerts")
news = load("trader-news", "news")
QUOTES = os.path.join(FIX, "kite", "kite-quotes.json")
NEWS = os.path.join(FIX, "news")


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rules = os.path.join(self.tmp, "alerts.json")
        self.state = os.path.join(self.tmp, "state.json")
        self.prices = os.path.join(self.tmp, "prices.json")
        self.quotes = os.path.join(self.tmp, "kite-quotes.json")
        with open(self.quotes, "w") as fh:
            json.dump({"data": {"NSE:TITAN": {"last_price": 4650.0, "last_trade_time": "2026-11-23T12:00:00+05:30",
                                              "ohlc": {"open": 4620, "high": 4686.7, "low": 4615.3, "close": 4600},
                                              "lower_circuit_limit": 4140, "upper_circuit_limit": 5060}}}, fh)
        plan = os.path.join(self.tmp, "plan.json")
        with open(plan, "w") as fh:
            json.dump({"symbol": "TITAN", "date": "2026-11-23", "stop": 4650.6, "target": 4720.8,
                       "flat_by": "15:10"}, fh)
        code, _, err = run(alerts, ["add", "--from-plan", "--plan", plan, "--rules", self.rules,
                                    "--state", self.state])
        self.assertEqual(code, 0, err)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, now):
        return run(alerts, ["check", "--rules", self.rules, "--state", self.state, "--source", "kite",
                            "--kite-file", self.quotes, "--prices-out", self.prices, "--now", now])

    def test_the_kite_quote_answer(self):
        with open(QUOTES) as fh:
            q = alerts.parse_kite_quotes(fh.read())
        self.assertEqual(list(q), ["RELIANCE"])
        self.assertEqual((q["RELIANCE"]["price"], q["RELIANCE"]["source"]), (1351.0, "kite"))
        quotes, errors = alerts.get_quotes(["RELIANCE", "TCS"], "kite", kite_file=QUOTES)
        self.assertEqual(list(quotes), ["RELIANCE"])
        self.assertEqual(errors, ["the Kite quote file has no quote for TCS"])
        quotes, errors = alerts.get_quotes(["RELIANCE"], "kite", kite_file=os.path.join(self.tmp, "none.json"))
        self.assertIn("ask Claude to fetch the quotes with the Kite connector", errors[0])

    def test_stop_rings_once_and_writes_circuits(self):
        code, out, _ = self.check("2026-11-23 12:00")
        self.assertEqual(code, 0)
        self.assertIn("ALERT TITAN is Rs 4650.00: at or below your stop Rs 4650.60", out)
        self.assertIn("GTT's stop and target already sit at Kite", out)
        with open(self.prices) as fh:
            d = json.load(fh)["detail"]["TITAN"]
        self.assertEqual((d["lower_circuit"], d["upper_circuit"], d["source"]), (4140, 5060, "kite"))
        code, out, _ = self.check("2026-11-23 12:05")
        self.assertEqual(code, 1)                                           # it rang already

    def test_flat_by_rings_at_15_10_ist(self):
        self.check("2026-11-23 12:00")
        code, out, _ = self.check("2026-11-23 15:10")
        self.assertEqual(code, 0)
        self.assertIn("Flat by close: it is 15:10 IST (set for 15:10), the market closes at 15:30.", out)
        self.assertIn("delete its GTT first", out)

    def test_nothing_rings_on_a_holiday(self):
        code, out, _ = self.check("2026-11-24 15:10")
        self.assertEqual(code, 1)
        self.assertIn("NSE closed", out)

    def test_clock_cli(self):
        code, out, _ = run(alerts, ["clock", "--now", "2026-11-24 09:00"])
        self.assertEqual(code, 1)
        self.assertIn("NSE closed, NSE holiday: Prakash Gurpurb Sri Guru Nanak Dev.", out)
        self.assertIn("Next open: 2026-11-25 09:15 IST.", out)


class News(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "news.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_news(self, *extra):
        return run(news, ["--tickers", "TITAN", "--offline", NEWS, "--state", self.state, "--no-moves",
                          "--now", "2026-11-23T11:00:00Z", "--json"] + list(extra))

    def test_yahoo_and_google_news_merged_and_tagged(self):
        code, out, err = self.run_news()
        self.assertEqual(code, 0, err)
        items = json.loads(out)["items"]
        titles = [i["title"] for i in items]
        # the results story is in both feeds: shown once, the Google copy without " - Example Times"
        self.assertEqual(sum(1 for t in titles if t.startswith("Titan Company Q2 results")), 1)
        self.assertEqual(titles[0], "Nifty ends lower as FII selling continues")      # newest first
        tags = {i["title"]: i["tags"] for i in items}
        self.assertIn("earnings", tags["Titan Company Q2 results: profit rises, jewellery sales strong"])
        self.assertIn("board", tags["Board meeting on dividend next week, says Titan"])
        self.assertIn("capital", tags["Board meeting on dividend next week, says Titan"])
        self.assertIn("macro", tags["Nifty ends lower as FII selling continues"])
        self.assertIn("analyst", tags["Brokerage raises target price on Titan (NSE: TITAN)"])

    def test_seen_items_show_once(self):
        self.run_news()
        code, out, _ = self.run_news()
        self.assertEqual(code, 1)
        self.assertFalse([i for i in json.loads(out)["items"] if i["new"]])

    def test_feed_urls(self):
        self.assertEqual(news.YAHOO % "M%26M.NS",
                         "https://feeds.finance.yahoo.com/rss/2.0/headline?s=M%26M.NS&region=IN&lang=en-IN")
        self.assertEqual(news.google_query("TITAN"), "%22TITAN%22+NSE")
        self.assertEqual(news.google_query("TITAN", "Titan Company"), "%22Titan+Company%22+NSE")


if __name__ == "__main__":
    unittest.main()
