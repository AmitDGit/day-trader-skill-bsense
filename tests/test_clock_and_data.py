"""What every tool shares: the IST clock, the NSE calendar, NSE symbols and Kite candles."""

import datetime
import json
import os
import unittest

from _load import FIX, load

DT = datetime.datetime
TOOLS = {
    "scan": load("trader-scanner", "scan"),
    "entry": load("trader-entry", "entry"),
    "exit": load("trader-exit", "exit"),
    "tm": load("trader-timemachine", "timemachine"),
    "alerts": load("trader-alerts", "alerts"),
    "risk": load("trader-risk", "check"),
    "size": load("trader-budget", "size"),
    "ticket": load("trader-broker", "ticket"),
    "news": load("trader-news", "news"),
}
KITE_TITAN = os.path.join(FIX, "kite", "TITAN-2026-11-23-5minute.json")


class Clock(unittest.TestCase):
    def test_ist_is_utc_plus_five_thirty_all_year(self):
        for name, m in TOOLS.items():
            for month in (1, 6, 11):
                self.assertEqual(m.to_ist(DT(2026, month, 2, 3, 45)), DT(2026, month, 2, 9, 15), name)
            if hasattr(m, "ist_to_utc"):
                self.assertEqual(m.ist_to_utc(DT(2026, 11, 23, 15, 30)), DT(2026, 11, 23, 10, 0), name)

    def test_the_session_is_9_15_to_15_30(self):
        for name in ("scan", "entry", "exit", "alerts", "risk"):
            m = TOOLS[name]
            self.assertEqual(m.OPEN, datetime.time(9, 15), name)
            self.assertEqual(m.CLOSE, datetime.time(15, 30), name)
        tm = TOOLS["tm"]
        self.assertEqual((tm.OPEN_MIN, tm.CLOSE_MIN, tm.SESSION_BARS), (555, 930, 75))

    def test_nse_holidays_2026(self):
        for name in ("scan", "entry", "exit", "alerts", "risk"):
            m = TOOLS[name]
            self.assertEqual(len(m.NSE_HOLIDAYS), 16, name)
            self.assertIn("2026-11-24", m.NSE_HOLIDAYS, name)          # Guru Nanak Jayanti
            self.assertNotIn("2026-11-26", m.NSE_HOLIDAYS, name)       # US Thanksgiving is a normal day here
        a = TOOLS["alerts"]
        self.assertEqual(a.trading_day(datetime.date(2026, 11, 24)), (False, "NSE holiday: Prakash Gurpurb "
                                                                      "Sri Guru Nanak Dev"))
        self.assertEqual(a.trading_day(datetime.date(2026, 11, 23)), (True, ""))
        self.assertEqual(a.trading_day(datetime.date(2026, 11, 28))[1], "weekend")

    def test_market_status_and_next_open(self):
        a = TOOLS["alerts"]
        st = a.market_status(a.parse_now("2026-11-23 10:15"))
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:30"))
        holiday = a.market_status(a.parse_now("2026-11-24 10:15"))
        self.assertFalse(holiday["open"])
        self.assertEqual(holiday["next_open"], "2026-11-25 09:15")
        late = a.market_status(a.parse_now("2026-11-27 15:30"))
        self.assertEqual((late["open"], late["next_open"]), (False, "2026-11-30 09:15"))
        self.assertFalse(a.market_status(a.parse_now("2027-01-04 10:00"))["calendar_known"])

    def test_parse_now_takes_ist_or_an_offset(self):
        for name in ("alerts", "risk", "ticket", "scan"):
            m = TOOLS[name]
            self.assertEqual(m.parse_now("2026-11-23 10:15"), DT(2026, 11, 23, 4, 45), name)
            self.assertEqual(m.parse_now("2026-11-23T04:45:00Z"), DT(2026, 11, 23, 4, 45), name)
            self.assertEqual(m.parse_now("2026-11-23T10:15:00+05:30"), DT(2026, 11, 23, 4, 45), name)
        e = TOOLS["entry"]
        self.assertEqual(e.parse_now("2026-11-23 10:15 IST"), DT(2026, 11, 23, 4, 45))


class Symbols(unittest.TestCase):
    def test_yahoo_spelling(self):
        for name in ("scan", "entry", "exit", "tm", "alerts", "news"):
            m = TOOLS[name]
            self.assertEqual(m.yahoo_symbol("RELIANCE"), "RELIANCE.NS", name)
            self.assertEqual(m.yahoo_symbol("nse:m&m"), "M&M.NS", name)
            self.assertEqual(m.yahoo_symbol("BSE:SBIN"), "SBIN.BO", name)
            self.assertEqual(m.yahoo_symbol("BAJAJ-AUTO"), "BAJAJ-AUTO.NS", name)
            self.assertEqual(m.yahoo_symbol("^NSEI"), "^NSEI", name)
            self.assertEqual(m.plain_symbol("TITAN.NS"), "TITAN", name)
            self.assertEqual(m.plain_symbol("NSE:TITAN"), "TITAN", name)

    def test_urls_escape_the_ampersand(self):
        self.assertIn("/chart/M%26M.NS?", TOOLS["entry"].chart_path("M&M", "1d", "5m"))
        self.assertIn("/chart/M%26M.NS?", TOOLS["tm"].chart_url("M&M"))
        self.assertIn("/chart/BAJAJ-AUTO.NS?", TOOLS["alerts"].yahoo_url("BAJAJ-AUTO"))
        self.assertIn("symbols=RELIANCE.NS,M%26M.NS&", TOOLS["scan"].spark_path(["RELIANCE", "M&M"], "1d", "5m"))


class KiteCandles(unittest.TestCase):
    def setUp(self):
        with open(KITE_TITAN, encoding="utf-8") as fh:
            self.doc = json.load(fh)

    def test_the_connector_answer_becomes_a_chart(self):
        for name in ("scan", "entry", "exit", "tm"):
            ch = TOOLS[name].kite_chart(self.doc, "TITAN")
            r = ch["chart"]["result"][0]
            self.assertEqual(r["meta"]["symbol"], "TITAN.NS", name)
            self.assertEqual(r["meta"]["currency"], "INR", name)
            self.assertEqual(len(r["timestamp"]), 72, name)
            self.assertEqual(r["timestamp"][0], 1795405500, name)           # 2026-11-23 09:15 IST = 03:45 UTC
            q = r["indicators"]["quote"][0]
            self.assertEqual((q["open"][0], q["high"][0], q["low"][0], q["close"][0], q["volume"][0]),
                             (4620, 4677.4, 4615.3, 4660.3, 42830), name)

    def test_the_kite_connect_api_shape_and_bare_lists(self):
        k = TOOLS["entry"]
        api = {"status": "success", "data": {"candles": [["2026-11-23T09:15:00+0530", 4620, 4677.4, 4615.3,
                                                           4660.3, 42830]]}}
        r = k.kite_chart(api, "TITAN")["chart"]["result"][0]
        self.assertEqual((r["timestamp"], r["indicators"]["quote"][0]["close"]), ([1795405500], [4660.3]))
        r = k.kite_chart(self.doc["data"][:2], "TITAN")["chart"]["result"][0]
        self.assertEqual(len(r["timestamp"]), 2)
        naive = [{"date": "2026-11-23 09:15:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}]
        self.assertEqual(k.kite_chart(naive, "X")["chart"]["result"][0]["timestamp"], [1795405500])

    def test_other_shapes_are_left_alone(self):
        k = TOOLS["scan"]
        self.assertIsNone(k.kite_chart({"chart": {"result": []}}))
        self.assertIsNone(k.kite_chart({"spark": {}}))
        self.assertIsNone(k.kite_chart({"data": []}))
        self.assertIsNone(k.kite_chart([{"x": 1}]))


class Money(unittest.TestCase):
    def test_rupees_in_indian_grouping(self):
        for name in ("scan", "exit", "risk", "size", "ticket"):
            m = TOOLS[name]
            self.assertEqual(m.inr(123456789.5), "Rs 12,34,56,789.50", name)
            self.assertEqual(m.inr(99999), "Rs 99,999.00", name)
            self.assertEqual(m.inr(-1500, drop_zero_paise=True), "-Rs 1,500", name)
            self.assertEqual(m.inr(950.25), "Rs 950.25", name)
        self.assertEqual(TOOLS["size"].money(100000), "Rs 1,00,000")


if __name__ == "__main__":
    unittest.main()
