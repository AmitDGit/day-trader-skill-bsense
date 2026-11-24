"""One NSE day trade end to end on real Kite candles: TITAN, Monday 23 November 2026.

entry (close above 4,670) -> exit plan -> budget -> risk -> broker ticket (dry run).
Then each tool's refusals."""

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load

entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
size = load("trader-budget", "size")
risk = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
alerts = load("trader-alerts", "alerts")

TITAN = os.path.join(FIX, "kite", "TITAN-2026-11-23-5minute.json")
QUOTES = os.path.join(FIX, "kite", "kite-quotes.json")
NOW = "2026-11-23 11:40"


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        t = cls.tmp
        os.makedirs(os.path.join(t, "state"))
        cls.p = {k: os.path.join(t, v) for k, v in (
            ("entry", "entry.json"), ("plan", "plan.json"), ("orders", "orders.json"), ("config", "config.json"),
            ("prices", "prices.json"), ("risk", "state/risk.json"), ("broker", "state/broker.json"),
            ("portfolio", "portfolio.json"), ("none", "missing.json"))}
        shutil.copy(os.path.join(ROOT, "trader-budget", "config.example.json"), cls.p["config"])
        cls.codes = {}
        cls.codes["entry"], cls.entry_out, _ = run(entry, [
            "check", "TITAN", "--offline", TITAN, "--now", NOW, "--setup", "level", "--level", "4670",
            "--write", cls.p["entry"]])
        cls.codes["exit"], cls.exit_out, _ = run(exitp, [
            "plan", "--from", cls.p["entry"], "--stop", "pct:0.5", "--target", "2R", "--now", NOW,
            "--write", cls.p["plan"]])
        cls.codes["size"], cls.size_out, _ = run(size, [
            "--plan", cls.p["plan"], "--config", cls.p["config"], "--now", NOW, "--write", cls.p["orders"]])
        cls.codes["risk"], cls.risk_out, _ = run(risk, [
            "--orders", cls.p["orders"], "--config", cls.p["config"], "--portfolio", cls.p["none"],
            "--prices", cls.p["none"], "--state", cls.p["broker"], "--out", cls.p["risk"], "--now", NOW])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def read(self, k):
        with open(self.p[k], encoding="utf-8") as fh:
            return json.load(fh)

    def tk(self, *argv):
        base = ["--orders", self.p["orders"], "--config", self.p["config"], "--risk", self.p["risk"],
                "--state", self.p["broker"], "--now", "2026-11-23 11:41"]
        return run(ticket, list(argv[:1]) + base + list(argv[1:]))

    def test_1_entry_triggers_on_the_1130_bar(self):
        self.assertEqual(self.codes["entry"], 0)
        e = self.read("entry")
        self.assertEqual((e["symbol"], e["status"], e["time"], e["price"], e["source"]),
                         ("TITAN", "triggered", "11:35 AM", 4674.0, "kite"))
        self.assertIn("(Kite candles)", self.entry_out)

    def test_2_the_plan_is_on_the_tick(self):
        self.assertEqual(self.codes["exit"], 0)
        pl = self.read("plan")
        # 4674 x 0.995 = 4650.63, down to the 0.10 tick of the Rs 1,000 to 5,000 band
        self.assertEqual((pl["entry"], pl["stop"], pl["target"], pl["risk_per_share"]),
                         (4674.0, 4650.6, 4720.8, 23.4))
        self.assertEqual(pl["flat_by"], "15:10")
        self.assertIn("rounded down to the 0.1 tick", self.exit_out)
        self.assertIn("Zerodha squares off MIS at about 15:20", self.exit_out)

    def test_3_sized_in_rupees_with_zerodha_charges(self):
        self.assertEqual(self.codes["size"], 0)
        o = self.read("orders")["orders"][0]
        self.assertEqual((o["exchange"], o["symbol"], o["qty"], o["product"], o["order_class"]),
                         ("NSE", "TITAN", "16", "MIS", "bracket"))
        self.assertEqual((o["stop_loss_stop_price"], o["take_profit_limit_price"]), ("4650.60", "4720.80"))
        self.assertEqual(o["plan"]["costs_at_stop"], 73.63)
        self.assertEqual(o["plan"]["net_loss_at_stop"], 448.03)
        self.assertTrue(self.read("orders")["dry_run"])
        self.assertIn("Size: 16 shares of TITAN = Rs 74,784 at 4674.00.", self.size_out)

    def test_4_risk_passes_with_charges_in_the_max_loss(self):
        self.assertEqual(self.codes["risk"], 0, self.risk_out)
        r = self.read("risk")["results"][0]
        self.assertEqual((r["verdict"], r["max_loss"], r["product"], r["exchange"]), ("PASS", 448.03, "MIS", "NSE"))

    def test_5_the_ticket_is_two_kite_calls(self):
        code, out, _ = self.tk("show", "--index", "1", "--json")
        self.assertEqual(code, 0)
        t = json.loads(out)
        self.assertTrue(t["ready"] and t["dry_run"])
        self.assertEqual(t["tool_input"], {
            "mode": "place", "variety": "regular", "exchange": "NSE", "tradingsymbol": "TITAN",
            "transaction_type": "BUY", "quantity": 16, "product": "MIS", "order_type": "MARKET",
            "validity": "DAY", "tag": "daytrader", "market_protection": -1})
        self.assertEqual(t["gtt_input"], {
            "mode": "place", "exchange": "NSE", "tradingsymbol": "TITAN", "transaction_type": "SELL",
            "product": "MIS", "trigger_type": "two-leg", "last_price": 4674,
            "lower_trigger_value": 4650.6, "lower_limit_price": 4627.3, "lower_quantity": 16,
            "upper_trigger_value": 4720.8, "upper_limit_price": 4720.8, "upper_quantity": 16})
        code, text, _ = self.tk("show")
        self.assertIn("DRY RUN, nothing is sent, Kite (Zerodha)", text)
        self.assertIn("Step 2, the exit, only once the entry has filled", text)

    def test_6_a_yes_in_a_dry_run_is_recorded_and_nothing_is_called(self):
        code, out, _ = self.tk("approve", "--index", "1", "--reply", "yes to all")
        self.assertEqual(code, 1)
        self.assertIn("a yes covers one order at a time", out)
        code, out, _ = self.tk("approve", "--index", "1", "--reply", "yes, 16 TITAN")
        self.assertEqual(code, 0, out)
        self.assertIn("Dry run (\"dry_run\": true): do NOT call Kite.", out)
        code, out, _ = self.tk("result", "--index", "1", "--status", "skipped", "--note", "dry run")
        self.assertEqual(code, 0)
        code, out, _ = self.tk("show", "--index", "1", "--json")
        self.assertIn("DONE: skipped", json.loads(out)["status"])


class Risk(unittest.TestCase):
    ORDER = {"exchange": "NSE", "symbol": "TITAN", "side": "buy", "qty": "16", "type": "limit",
             "limit_price": "4674.00", "time_in_force": "day", "product": "MIS", "order_class": "bracket",
             "take_profit_limit_price": "4720.80", "stop_loss_stop_price": "4650.60"}
    CFG = {"budget": 100000, "max_order_inr": 80000, "max_loss_per_trade_inr": 500}

    def check(self, order=None, cfg=None, now="2026-11-23 11:40", **kw):
        o = dict(self.ORDER)
        o.update(order or {})
        c = dict(self.CFG)
        c.update(cfg or {})
        res = risk.check([o], c, now=risk.parse_now(now), **kw)
        return res["results"][0], res

    def test_the_clean_order_passes(self):
        r, res = self.check()
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_off_tick_prices_are_blocked(self):
        r, _ = self.check({"stop_loss_stop_price": "4650.63"})
        self.assertIn("tick: stop_loss_stop_price 4650.63 is not a multiple of the 0.10 tick; Kite rejects it",
                      r["reasons"])
        r, _ = self.check({"symbol": "WIPRO", "limit_price": "187.29", "stop_loss_stop_price": "186.01",
                           "take_profit_limit_price": "189.85", "qty": "100"})
        self.assertFalse([x for x in r["reasons"] if x.startswith("tick")])      # 0.01 under Rs 250

    def test_charges_count_toward_the_max_loss(self):
        r, _ = self.check({"qty": "20"})        # 20 x 23.40 = 468 gross, about 556 with charges
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertTrue(any(x.startswith("loss: 20 shares x 23.40 risk a share = Rs 468 at the stop plus")
                            for x in r["reasons"]), r["reasons"])
        r, _ = self.check({"qty": "20"}, {"include_costs": False})
        self.assertFalse([x for x in r["reasons"] if x.startswith("loss")])

    def test_kite_formats(self):
        r, _ = self.check({"notional": "50000", "qty": None, "order_class": None,
                           "take_profit_limit_price": None, "stop_loss_stop_price": None})
        self.assertTrue(any("Kite takes a number of shares, not a rupee amount" in x for x in r["reasons"]))
        r, _ = self.check({"time_in_force": "gtc"})
        self.assertIn("format: time_in_force 'gtc': Kite takes day or ioc", r["reasons"])
        r, _ = self.check({"product": "NRML"})
        self.assertIn("format: product 'NRML': MIS (intraday) or CNC (delivery)", r["reasons"])
        r, _ = self.check({"exchange": "NASDAQ"})
        self.assertIn("format: exchange 'NASDAQ': this pack trades NSE or BSE equity", r["reasons"])
        r, _ = self.check({"symbol": "NIFTY26NOV24000CE"})
        self.assertTrue(any(x.startswith("asset: NIFTY26NOV24000CE is a futures or options contract")
                            for x in r["reasons"]))
        r, _ = self.check({"symbol": "M&M", "limit_price": "3487.40", "stop_loss_stop_price": "3470.00",
                           "take_profit_limit_price": "3522.20", "qty": "10"})
        self.assertFalse([x for x in r["reasons"] if x.startswith("asset")])

    def test_circuit_limits_from_a_kite_quote(self):
        with open(QUOTES, encoding="utf-8") as fh:
            q = alerts.parse_kite_quotes(fh.read())["RELIANCE"]
        self.assertEqual((q["lower_circuit"], q["upper_circuit"], q["prev_close"]), (1215.9, 1486.1, 1351))
        order = {"symbol": "RELIANCE", "limit_price": "1480.00", "stop_loss_stop_price": "1470.00",
                 "take_profit_limit_price": "1500.00", "qty": "10"}
        r, _ = self.check(order, circuits={"RELIANCE": (1215.9, 1486.1)})
        self.assertIn("circuit: the target 1500.00 is outside today's circuit band 1215.90 to 1486.10", r["reasons"])
        self.assertTrue(any("within 1% of its upper circuit 1486.10" in x for x in r["reasons"]))

    def test_the_nse_window(self):
        r, _ = self.check(now="2026-11-23 09:20")
        self.assertIn("window: no new entries before 09:30 IST (it is 09:20)", r["reasons"])
        r, _ = self.check(now="2026-11-23 14:50")
        self.assertIn("window: no new entries after 14:45 IST (it is 14:50)", r["reasons"])
        r, _ = self.check(now="2026-11-24 11:00")
        self.assertTrue(any("market is closed today (NSE holiday" in x for x in r["reasons"]))

    def test_flat_by_after_the_mis_square_off_warns(self):
        _, res = self.check(cfg={"flat_by": "15:25"})
        self.assertTrue(any("not before Zerodha's MIS auto square-off at 15:20" in w for w in res["warnings"]))

    def test_live_warns(self):
        _, res = self.check(cfg={"dry_run": False})
        self.assertTrue(any(w.startswith("LIVE") for w in res["warnings"]))

    def test_fingerprint_is_shared_with_the_broker(self):
        self.assertEqual(risk.ORDER_FIELDS, ticket.ORDER_FIELDS)
        self.assertEqual(risk.fingerprint(self.ORDER), ticket.fingerprint(self.ORDER))
        edited = dict(self.ORDER, qty="17")
        self.assertNotEqual(risk.fingerprint(self.ORDER), risk.fingerprint(edited))


class Budget(unittest.TestCase):
    PLAN = {"symbol": "TITAN", "side": "buy", "date": "2026-11-23", "setup": "level", "entry": 4674.0,
            "stop": 4650.6, "target": 4720.8, "flat_by": "15:10"}

    def test_charges(self):
        c = size.trade_costs(16, 4674.0, 4650.6)
        self.assertEqual((c["brokerage"], c["stt"], c["stamp"], c["total"]), (40.0, 18.6, 2.24, 73.63))
        small = size.trade_costs(1, 300.0, 299.0)          # 0.03% of Rs 300 is under the Rs 20 cap
        self.assertEqual(small["brokerage"], 0.18)
        self.assertEqual(size.trade_costs(0, 1, 1)["total"], 0.0)

    def test_the_max_loss_binds_after_charges(self):
        s = size.size_trade(self.PLAN, {"budget": 1000000, "max_order_inr": 1000000, "max_position_pct": 100,
                                        "max_loss_per_trade_inr": 500})
        # 500 / 23.40 = 21 shares gross; with the charges (about Rs 77 for 18) only 18 fit
        self.assertEqual((s["qty"], s["bound_by"], s["net_loss_at_stop"]), (18, "max loss", 498.13))
        self.assertLessEqual(s["net_loss_at_stop"], 500)
        s = size.size_trade(self.PLAN, {"budget": 1000000, "max_order_inr": 1000000, "max_position_pct": 100,
                                        "max_loss_per_trade_inr": 500, "include_costs": False})
        self.assertEqual(s["qty"], 21)

    def test_too_far_a_stop_is_a_refusal(self):
        s = size.size_trade(dict(self.PLAN, stop=4100.0, target=5800.0), {"budget": 100000,
                                                                          "max_loss_per_trade_inr": 500})
        self.assertEqual(s["qty"], 0)
        self.assertIn("more than your Rs 500 max loss per trade", s["refusal"])
        self.assertIsNone(size.bracket_order(s))


class Exit(unittest.TestCase):
    def test_ticks_by_price_band(self):
        D = exitp.D
        self.assertEqual([str(exitp.tick_for(D(p))) for p in (187, 817.8, 4674, 6000, 14010, 25000)],
                         ["0.01", "0.05", "0.10", "0.50", "1.00", "5.00"])
        c = exitp.compute(817.8, "pct", D("1"), "r", D("2"))
        self.assertEqual((str(c["stop"]), str(c["target"])), ("809.60", "834.20"))   # 809.622 down, 834.2 on the 0.05
        c = exitp.compute(4674, "pct", D("0.5"), "r", D("2"), tick=D("0.05"))
        self.assertEqual(str(c["stop"]), "4650.60")

    def test_atr_on_kite_candles(self):
        code, out, err = run(exitp, ["plan", "--symbol", "TITAN", "--entry", "4674", "--setup", "level",
                                     "--date", "2026-11-23", "--entry-bar", "27", "--stop", "atr:2",
                                     "--offline", TITAN, "--now", NOW, "--json"])
        self.assertEqual(code, 0, err)
        pl = json.loads(out)
        self.assertEqual((pl["atr_bars"], pl["stop"]), (14, 4647.6))


class Entry(unittest.TestCase):
    def check(self, now, *extra):
        return run(entry, ["check", "TITAN", "--offline", TITAN, "--now", now, "--json"] + list(extra))

    def test_the_range_forms_then_waits_then_expires(self):
        code, out, _ = self.check("2026-11-23 09:25")
        self.assertEqual((code, json.loads(out)["phase"]), (1, "forming"))
        code, out, _ = self.check("2026-11-23 10:15")
        r = json.loads(out)
        self.assertEqual((r["status"], r["opening_range"]["high"], r["opening_range"]["low"]),
                         ("waiting", 4678.1, 4615.3))
        code, out, _ = self.check("2026-11-23 14:50")
        self.assertEqual(json.loads(out)["status"], "expired")      # the 15:05 close above came after 14:45

    def test_a_holiday(self):
        code, out, _ = self.check("2026-11-24 10:00")
        r = json.loads(out)
        self.assertEqual((r["status"], r["next_open"]), ("no-data", "2026-11-25 09:15"))

    def test_the_file_must_be_the_symbol(self):
        code, _, err = run(entry, ["check", "RELIANCE", "--offline", TITAN, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("the chart file holds TITAN, not RELIANCE", err)


if __name__ == "__main__":
    unittest.main()
