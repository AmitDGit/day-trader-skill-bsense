import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import load

ticket = load("trader-broker", "ticket")
risk = load("trader-risk", "check")

ORDER = {"exchange": "NSE", "symbol": "M&M", "side": "buy", "qty": "10", "type": "limit", "limit_price": "3487.40",
         "time_in_force": "day", "product": "MIS", "order_class": "bracket", "take_profit_limit_price": "3522.20",
         "stop_loss_stop_price": "3470.00", "plan": {"entry": 3487.4, "stop": 3470.0, "max_loss": 174.0}}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ticket.main(argv)
    return code, out.getvalue(), err.getvalue()


class Calls(unittest.TestCase):
    def test_limit_entry_and_the_gtt(self):
        self.assertEqual(ticket.tool_input(ORDER), {
            "mode": "place", "variety": "regular", "exchange": "NSE", "tradingsymbol": "M&M",
            "transaction_type": "BUY", "quantity": 10, "product": "MIS", "order_type": "LIMIT", "validity": "DAY",
            "tag": "daytrader", "price": 3487.4})
        g = ticket.gtt_input(ORDER, last_price=3490.1)
        self.assertEqual((g["last_price"], g["lower_trigger_value"], g["lower_limit_price"], g["upper_trigger_value"]),
                         (3490.1, 3470, 3452.6, 3522.2))      # 3470 less 0.5% = 3452.65, down to the 0.10 tick
        self.assertIsNone(ticket.gtt_input(dict(ORDER, order_class=None, take_profit_limit_price=None,
                                                stop_loss_stop_price=None)))

    def test_stop_orders_are_sl_and_sl_m(self):
        sl = ticket.tool_input({"symbol": "ITC", "side": "sell", "qty": "5", "type": "stop_limit",
                                "stop_price": "298.50", "limit_price": "298.00", "time_in_force": "day"})
        self.assertEqual((sl["order_type"], sl["trigger_price"], sl["price"]), ("SL", 298.5, 298))
        slm = ticket.tool_input({"symbol": "ITC", "side": "sell", "qty": "5", "type": "stop", "stop_price": "298.50"})
        self.assertEqual((slm["order_type"], slm["market_protection"]), ("SL-M", -1))

    def test_plain_words_and_yes(self):
        self.assertTrue(ticket.plain(ORDER).startswith("BUY 10 M&M on NSE, limit 3487.40, MIS intraday, good for today"))
        self.assertTrue(ticket.parse_yes("yes", ORDER, ["M&M", "TITAN"])[0])
        ok, why = ticket.parse_yes("yes TITAN", ORDER, ["M&M", "TITAN"])
        self.assertEqual((ok, why), (False, "the reply names TITAN, but this order is for M&M"))
        self.assertFalse(ticket.parse_yes("yes 20 shares", ORDER)[0])
        self.assertFalse(ticket.parse_yes("ok go", ORDER)[0])

    def test_dry_run_is_the_default(self):
        self.assertTrue(ticket.dry_run({}))
        self.assertFalse(ticket.dry_run({"dry_run": False}))
        self.assertFalse(ticket.dry_run({"paper": False}))              # an old config


class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.tmp, n)
        self.p = {"orders": j("orders.json"), "config": j("config.json"), "risk": j("risk.json"),
                  "state": j("broker.json"), "portfolio": j("portfolio.json"), "plan": j("plan.json")}
        with open(self.p["orders"], "w") as fh:
            json.dump({"orders": [ORDER]}, fh)
        with open(self.p["config"], "w") as fh:
            json.dump({"budget": 100000, "dry_run": False}, fh)
        res = risk.check([ORDER], {"budget": 100000}, now=risk.parse_now("2026-11-23 11:40"))
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])
        with open(self.p["risk"], "w") as fh:
            json.dump(res, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def tk(self, *argv):
        base = ["--orders", self.p["orders"], "--config", self.p["config"], "--risk", self.p["risk"],
                "--state", self.p["state"], "--now", "2026-11-23 11:41"]
        return run(list(argv[:1]) + base + list(argv[1:]))

    def test_a_live_yes_gives_the_two_calls_in_order(self):
        code, text, _ = self.tk("show")
        self.assertIn("LIVE, YOUR ZERODHA ACCOUNT, REAL MONEY", text)
        self.assertIn("The GTT has no Kite approval", text)
        code, out, _ = self.tk("approve", "--index", "1", "--reply", "yes")
        self.assertEqual(code, 0, out)
        self.assertIn("Now call the Kite connector's orders tool with exactly:", out)
        self.assertIn("Never repeat the place call.", out)
        self.assertIn("Once the entry has FILLED", out)
        code, out, _ = self.tk("result", "--index", "1", "--status", "placed", "--broker-id", "2611230001",
                               "--gtt-id", "998877")
        self.assertEqual(code, 0)
        with open(self.p["state"]) as fh:
            last = json.load(fh)["orders"][-1]
        self.assertEqual((last["broker_order_id"], last["gtt_id"]), ("2611230001", "998877"))
        code, out, err = run(["flatten", "--symbol", "M&M", "--qty", "10", "--orders", os.path.join(self.tmp, "f.json"),
                              "--config", self.p["config"], "--portfolio", self.p["portfolio"], "--plan",
                              self.p["plan"], "--state", self.p["state"], "--now", "2026-11-23 15:10"])
        self.assertEqual(code, 0, err)
        self.assertIn("FIRST delete the open GTT for M&M", out)
        self.assertIn("recorded: 998877", out)
        with open(os.path.join(self.tmp, "f.json")) as fh:
            o = json.load(fh)["orders"][0]
        self.assertEqual((o["side"], o["qty"], o["product"], o["exchange"]), ("sell", "10", "MIS", "NSE"))


if __name__ == "__main__":
    unittest.main()
