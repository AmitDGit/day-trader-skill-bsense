#!/usr/bin/env python3
"""Order tickets and the decision log for trader-broker. Standard library only.

This tool never talks to a broker and never places anything. It does its
work around the one moment that matters, your yes:

  show      renders each proposed order as a plain-English ticket plus the
            exact arguments Claude will send to the Kite connector: step 1,
            the `orders` place call (MIS entry), and step 2, after the entry
            fills, the two-leg `gtt` (OCO stop and target). It shows the max
            loss at the stop with Zerodha's charges. In dry run (the
            default) it says so and nothing is sent. An order is READY only if trader-risk passed THIS
            exact order today (matched by fingerprint) and nobody has decided
            on it yet.
  approve   records your explicit yes for ONE order, with your reply word for
            word. It refuses "yes to all", "sure", "ok", a yes that names a
            different stock or amount, and any order that is not READY.
  decline   records a no.
  result    records what happened after the Allow once / Deny card:
            placed (with Kite's order id and --gtt-id), denied, failed or skipped.
  fill      records a fill in trader/portfolio.json (cash and shares).
  flatten   builds a sell ticket that closes a symbol's open position by
            flat_by. It still goes through trader-risk and your yes.
  log       prints today's decisions.

    python3 ticket.py show                    # every order, READY or not
    python3 ticket.py show --index 1 --json   # one ticket as JSON
    python3 ticket.py approve --index 1 --reply "yes"
    python3 ticket.py result --index 1 --status placed --broker-id 251123000123456 --gtt-id 3012345
    python3 ticket.py fill --symbol TITAN --side buy --qty 16 --price 4674.0
    python3 ticket.py flatten --symbol TITAN --qty 16
    python3 ticket.py log

Everything is written to trader/state/broker.json (append only). Dates are
IST dates; --now "2026-11-23 11:40" pins the clock.
"""

import argparse
import datetime
import hashlib
import math
import json
import os
import re
import sys

ORDER_FIELDS = ("exchange", "symbol", "side", "qty", "notional", "type", "time_in_force", "product",
                "limit_price", "stop_price", "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "ioc": "immediate or cancel"}
KITE_TYPES = {"market": "MARKET", "limit": "LIMIT", "stop": "SL-M", "stop_limit": "SL"}
PRODUCT_WORDS = {"MIS": "MIS intraday", "CNC": "CNC delivery"}
TAG = "daytrader"
# A GTT leg places a LIMIT order when it triggers. The stop leg's limit sits this
# far under the trigger so a falling price still fills it ("gtt_stop_buffer_pct").
GTT_STOP_BUFFER_PCT = 0.5
TICKS = ((250.0, 0.01), (1000.0, 0.05), (5000.0, 0.10), (10000.0, 0.50), (20000.0, 1.00), (None, 5.00))
YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if"}


class TicketError(Exception):
    pass


# ---------------------------------------------------------------- time (IST, no tz files)

def to_ist(utc):
    """naive UTC -> naive IST. India Standard Time is UTC+05:30 all year (no daylight saving)."""
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=5, minutes=30)


def ist_to_utc(local):
    return local - datetime.timedelta(hours=5, minutes=30)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as IST."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TicketError("--now wants a time like \"2026-10-19 10:15\" (IST) or ...Z (UTC)")
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def ist_iso(now_utc):
    """naive UTC -> "2026-10-19T10:15:00+05:30" (IST wall clock with its offset)."""
    return "%s+05:30" % to_ist(now_utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """The trading day a decision belongs to: its "date" (the day it was made under), else the day of "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

def fingerprint(order):
    """Same function as trader-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tick_for(price):
    for upper, tick in TICKS:
        if upper is None or float(price) < upper:
            return tick
    return 0.05


def floor_tick(x, tick):
    return round(math.floor(float(x) / tick + 1e-9) * tick, 2)


def _num_out(v):
    f = float(v)
    return int(f) if f == int(f) else round(f, 2)


def tool_input(order):
    """The entry: the exact arguments for the Kite connector's orders tool
    (mode=place). "why" and "plan" are ours and are never sent."""
    typ = str(order.get("type", "market")).lower()
    out = {"mode": "place", "variety": "regular",
           "exchange": str(order.get("exchange") or "NSE").upper(),
           "tradingsymbol": str(order.get("symbol", "")).upper(),
           "transaction_type": str(order.get("side", "")).upper(),
           "quantity": int(float(order.get("qty") or 0)),
           "product": str(order.get("product") or "MIS").upper(),
           "order_type": KITE_TYPES.get(typ, typ.upper()),
           "validity": str(order.get("time_in_force") or "day").upper(),
           "tag": TAG}
    if typ in ("limit", "stop_limit") and order.get("limit_price") is not None:
        out["price"] = _num_out(order["limit_price"])
    if typ in ("stop", "stop_limit") and order.get("stop_price") is not None:
        out["trigger_price"] = _num_out(order["stop_price"])
    if typ in ("market", "stop"):
        out["market_protection"] = -1          # Kite's automatic market protection
    return out


def gtt_input(order, last_price=None, buffer_pct=GTT_STOP_BUFFER_PCT):
    """The exit, for a bracket: the exact arguments for the Kite connector's gtt
    tool (mode=place), one two-leg (OCO) GTT. When one leg triggers Kite places
    its limit order and cancels the other. last_price is the price when the GTT
    is placed (Kite wants it); until then the entry stands in for it."""
    if not is_bracket(order):
        return None
    q = int(float(order.get("qty") or 0))
    stop = float(order["stop_loss_stop_price"])
    target = float(order["take_profit_limit_price"])
    long = str(order.get("side", "buy")).lower() == "buy"
    if order.get("stop_loss_limit_price") is not None:
        stop_limit = float(order["stop_loss_limit_price"])
    else:
        tick = tick_for(stop)
        gap = stop * float(buffer_pct) / 100.0
        stop_limit = floor_tick(stop - gap, tick) if long else round(math.ceil((stop + gap) / tick - 1e-9) * tick, 2)
    plan = order.get("plan") or {}
    ref = last_price if last_price is not None else (_f(order.get("limit_price")) or _f(plan.get("entry")))
    lower, upper = (stop, target) if long else (target, stop)
    lower_lim, upper_lim = (stop_limit, target) if long else (target, stop_limit)
    return {"mode": "place", "exchange": str(order.get("exchange") or "NSE").upper(),
            "tradingsymbol": str(order.get("symbol", "")).upper(),
            "transaction_type": "SELL" if long else "BUY", "product": str(order.get("product") or "MIS").upper(),
            "trigger_type": "two-leg", "last_price": _num_out(ref) if ref else None,
            "lower_trigger_value": _num_out(lower), "lower_limit_price": _num_out(lower_lim), "lower_quantity": q,
            "upper_trigger_value": _num_out(upper), "upper_limit_price": _num_out(upper_lim), "upper_quantity": q}


def inr_group(digits):
    """'1234567' -> '12,34,567': Indian grouping (thousands, then lakhs and crores)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(x, decimals=2, drop_zero_paise=False):
    """Rupees: 123456.5 -> 'Rs 1,23,456.50'. ASCII on purpose, so it prints on any console."""
    x = float(x)
    sign = "-" if x < 0 else ""
    s = ("%." + str(decimals) + "f") % abs(x)
    whole, _, frac = s.partition(".")
    if drop_zero_paise and frac and set(frac) == {"0"}:
        frac = ""
    return "%sRs %s%s" % (sign, inr_group(whole), "." + frac if frac else "")


def _money(v):
    return inr(v, drop_zero_paise=True)


def _p(v):
    return "%.2f" % float(v)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def max_loss(order):
    """(rupees, stop) lost if the stop fills exactly at the stop, or (None, stop).
    trader-budget's plan max_loss is gross; the plan's net_loss_at_stop adds the charges."""
    stop = _f(order.get("stop_loss_stop_price")) or _f((order.get("plan") or {}).get("stop"))
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop
    plan = order.get("plan") or {}
    if str(order.get("type", "market")) == "limit" and _f(order.get("limit_price")):
        entry = _f(order["limit_price"])
    elif _f(plan.get("max_loss")) is not None:
        return round(_f(plan["max_loss"]), 2), stop
    else:
        entry = _f(plan.get("entry"))
    if not entry:
        return None, stop
    risk = abs(entry - stop)
    return round(q * int(round(risk * 100)) / 100.0, 2), stop


def plain_parts(order):
    """The ticket in plain words, one part per line."""
    side = str(order.get("side", "")).upper()
    sym = order.get("symbol", "?")
    typ = str(order.get("type", "market"))
    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    product = PRODUCT_WORDS.get(str(order.get("product") or "MIS").upper(), order.get("product"))
    exch = str(order.get("exchange") or "NSE").upper()
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        parts = ["%s %s %s on %s, %s, %s, %s" % (side, _str_num(order.get("qty")), sym, exch, how, product, tif)]
        if order.get("stop_loss_stop_price") is not None:
            leg = "GTT stop-loss %s" % _p(order["stop_loss_stop_price"])
            if order.get("stop_loss_limit_price") is not None:
                leg += " (limit %s)" % _p(order["stop_loss_limit_price"])
            parts.append(leg)
        if order.get("take_profit_limit_price") is not None:
            parts.append("GTT target %s" % _p(order["take_profit_limit_price"]))
        loss, stop = max_loss(order)
        if loss is not None:
            net = _f((order.get("plan") or {}).get("net_loss_at_stop"))
            parts.append("max loss about %s if the stop fills at %s%s (it can fill worse in a fast market)"
                         % (_money(loss), _p(stop), (", %s with charges" % _money(net)) if net else ""))
        return parts
    if order.get("notional") is not None:
        what = "%s of %s" % (_money(order["notional"]), sym)
    else:
        q = _str_num(order.get("qty"))
        what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)
    if typ == "limit":
        how = "limit order at %s" % _money(order.get("limit_price"))
    elif typ == "stop":
        how = "SL-M order, trigger %s" % _money(order.get("stop_price"))
    elif typ == "stop_limit":
        how = "SL order, trigger %s, limit %s" % (_money(order.get("stop_price")), _money(order.get("limit_price")))
    else:
        how = "%s order" % typ.replace("_", " ")
    return ["%s %s on %s, %s, %s, %s" % (side, what, exch, how, product, tif)]


def plain(order):
    """SELL 7 shares of RELIANCE on NSE, market order, MIS intraday, good for today
    BUY 7 RELIANCE on NSE, market, MIS intraday, good for today / GTT stop-loss 1376.40 / GTT target ..."""
    return " / ".join(plain_parts(order))


def amount_numbers(order):
    nums = []
    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    loss, _ = max_loss(order)
    if loss is not None:
        nums.append(loss)
    return nums


def parse_yes(reply, order, batch_symbols=()):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-z']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" counts (not ok, sure, go, do it)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    sym = str(order.get("symbol", "")).upper()
    tokens = set(re.findall(r"[A-Z][A-Z&\-]{0,19}", raw.upper()))
    others = {s.upper() for s in batch_symbols} - {sym}
    named = tokens & others
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order)
        if not any(abs(n - w) < 0.005 for n in nums for w in want):
            return False, "the reply says %s, but this order is %s" % (
                ", ".join(_str_num(n) for n in nums), plain(order))
    return True, "explicit yes for %s" % plain(order)


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "broker state", required=False) or {"orders": []}


def latest(state, fp, today):
    """The latest decision recorded today for this fingerprint, or None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today):
    """(ready, label, risk_result)"""
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        if st == "approved":
            return False, "APPROVED by you at %s, waiting for the Kite orders call" % rec.get("at"), rv
        return False, "DONE: %s at %s" % (st, rec.get("at")), rv
    return True, "READY: trader-risk PASS, waiting for your yes", rv


def kind_of(order, rv):
    """entry or exit, as trader-risk saw it (older checks: a buy is an entry)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def dry_run(cfg):
    """Kite has no paper account: "dry_run": true (the default) means Claude shows
    the calls and never makes them. Older configs: "paper": true means the same."""
    if "dry_run" in cfg:
        return bool(cfg["dry_run"])
    return bool(cfg.get("paper", True))


def render(order, idx, total, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    dry = dry_run(cfg)
    acct = "DRY RUN, nothing is sent" if dry else "LIVE, YOUR ZERODHA ACCOUNT, REAL MONEY"
    lines = ["ORDER %d of %d, %s, Kite (Zerodha)" % (idx, total, acct)]
    for part in plain_parts(order):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  why: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  note: " + w)
    lines.append("  Step 1, the entry: the Kite connector's orders tool with exactly:")
    for l in json.dumps(tool_input(order), indent=2).splitlines():
        lines.append("    " + l)
    g = gtt_input(order, buffer_pct=cfg.get("gtt_stop_buffer_pct", GTT_STOP_BUFFER_PCT))
    if g:
        lines.append("  Step 2, the exit, only once the entry has filled: the gtt tool with exactly:")
        for l in json.dumps(g, indent=2).splitlines():
            lines.append("    " + l)
        lines.append("  Kite has no bracket order for stocks, so the stop and the target are one two-leg GTT:")
        lines.append("  when one leg triggers, Kite places its limit order and cancels the other. last_price")
        lines.append("  is the live price when the GTT is placed. The stop leg's limit sits under its trigger:")
        lines.append("  a sell limit under the market fills at the best bid, so it fills near the trigger in a")
        lines.append("  normal market, and a gap through that limit can leave it unfilled.")
    if ready:
        if dry:
            lines.append("  Dry run: reply \"yes\" to record your decision; Claude will not call Kite.")
            lines.append("  Set \"dry_run\": false in trader/config.json to trade for real.")
        else:
            lines.append("  Reply \"yes\" to place this one order%s, or \"no\" to skip it."
                         % (" and its GTT" if g else ""))
            lines.append("  Kite then shows its own approval for the entry. The GTT has no Kite approval")
            lines.append("  screen: your yes here is the only one, so read its two legs before you answer.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    loss, stop = max_loss(order)
    return {"index": idx, "ready": ready, "status": label, "plain": plain(order),
            "fingerprint": fingerprint(order), "dry_run": dry_run(cfg),
            "broker": "kite", "tool": "orders", "tool_input": tool_input(order),
            "gtt_tool": "gtt" if is_bracket(order) else None,
            "gtt_input": gtt_input(order, buffer_pct=cfg.get("gtt_stop_buffer_pct", GTT_STOP_BUFFER_PCT)),
            "why": order.get("why", ""), "bracket": is_bracket(order), "max_loss": loss, "stop": stop}


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date):
    """Record a filled order in trader/portfolio.json: cash and shares, with a
    cost-basis lot per buy (oldest lots are relieved first on a sell)."""
    pf = read_json(portfolio_path, "portfolio", required=False)
    if pf is None:
        budget = cfg.get("budget")
        if not budget:
            raise TicketError("no %s yet and no budget in the config to start it from" % portfolio_path)
        pf = {"cash": float(budget), "positions": []}
    symbol = symbol.upper()
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("a fill needs a positive qty and price")
    cost = round(qty * price, 2)
    pos = None
    for p in pf.setdefault("positions", []):
        if str(p.get("ticker", "")).upper() == symbol:
            pos = p
    if side == "buy":
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty, "cost": cost})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost, 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("cannot record selling %s %s: the portfolio holds %s"
                              % (_str_num(qty), symbol, pos.get("shares", 0) if pos else 0))
        left = qty
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost, 2)
    write_json(portfolio_path, pf)
    return pf


def log_fill(state_path, now, today, symbol, side, qty, price):
    """A fill in the log, so trader-risk can count day trades (a buy and a sell the same day)."""
    state = load_state(state_path)
    state.setdefault("orders", []).append({
        "at": ist_iso(now), "date": today, "status": "filled", "symbol": symbol.upper(), "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), symbol.upper(), _p(price))})
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a):
    now = parse_now(getattr(a, "now", None))
    today = getattr(a, "today", None) or to_ist(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today wants a date like 2026-10-19")
    return now, today


def _load(a):
    doc = read_json(a.orders, "orders file (run trader-budget, or ticket.py flatten, first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("no orders in %s" % a.orders)
    cfg = read_json(a.config, "config", required=False) or {}
    risk = read_json(a.risk, "risk check", required=False)
    state = load_state(a.state)
    now, today = _clock(a)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("say which order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nOne order at a time: a yes covers one ticket, never the batch. Education and tooling, "
          "not financial advice.")
    return 0 if any_ready else 1


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    ready, label, rv = status_of(order, risk, state, today)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (a.index, label))
    ok, why = parse_yes(a.reply, order, [o.get("symbol", "") for o in orders])
    if not ok:
        print("Not recorded: %s. Ask the user again with the ticket for order %d." % (why, a.index))
        return 1
    loss, stop = max_loss(order)
    rec = {"at": ist_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": loss, "stop": stop,
           "plain": plain(order), "status": "approved", "reply": a.reply,
           "dry_run": dry_run(cfg), "broker": "kite"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded your yes for order %d: %s." % (a.index, plain(order)))
    if dry_run(cfg):
        print("Dry run (\"dry_run\": true): do NOT call Kite. These are the calls a live run would make:")
        print(json.dumps(tool_input(order), indent=2))
        g = gtt_input(order, buffer_pct=cfg.get("gtt_stop_buffer_pct", GTT_STOP_BUFFER_PCT))
        if g:
            print(json.dumps(g, indent=2))
        print("Record it: ticket.py result --index %d --status skipped --note \"dry run\"" % a.index)
        return 0
    print("Now call the Kite connector's orders tool with exactly:")
    print(json.dumps(tool_input(order), indent=2))
    print("Kite shows its own approval (a form or a link). If it answers approval_required, nothing was placed")
    print("yet: share the link, then check orders mode=approval_status. Never repeat the place call.")
    if is_bracket(order):
        print("Once the entry has FILLED (orders mode=history), place the exit with the gtt tool, with the")
        print("live last_price from market mode=ltp:")
        print(json.dumps(gtt_input(order, buffer_pct=cfg.get("gtt_stop_buffer_pct", GTT_STOP_BUFFER_PCT)), indent=2))
    print("Then: ticket.py result --index %d --status placed|denied|failed --broker-id ORDER_ID [--gtt-id ID]"
          % a.index)
    return 0


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    rec = {"at": ist_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "plain": plain(order), "status": "declined", "reply": a.reply or "no"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded: you said no to order %d (%s). Nothing was sent." % (a.index, plain(order)))
    return 0


def cmd_result(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    fp = fingerprint(order)
    rec = latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no yes recorded today; a result can only follow an approval" % a.index)
    new = {"at": ist_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": rec["symbol"],
           "side": rec["side"], "plain": rec["plain"], "status": a.status}
    for k in ("qty", "kind", "max_loss", "stop"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    if a.broker_id:
        new["broker_order_id"] = a.broker_id
    if getattr(a, "gtt_id", None):
        new["gtt_id"] = a.gtt_id
    if a.note:
        new["note"] = a.note
    state["orders"].append(new)
    write_json(a.state, state)
    print("Recorded order %d as %s." % (a.index, a.status))
    if a.status == "placed" and a.filled_qty and a.filled_price:
        apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], a.filled_qty, a.filled_price, today)
        log_fill(a.state, now, today, rec["symbol"], rec["side"], a.filled_qty, a.filled_price)
        print("Added the fill to %s." % a.portfolio)
    elif a.status == "placed":
        print("When it fills, record it: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (rec["symbol"], rec["side"]))
        if rec.get("kind") == "entry" and is_bracket(order):
            print("When a GTT leg (the stop or the target) fills later, record that sell the same way.")
    return 0


def cmd_fill(a):
    cfg = read_json(a.config, "config", required=False) or {}
    now = parse_now(a.now)
    date = a.date or to_ist(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise TicketError("--date wants a date like 2026-10-19")
    pf = apply_fill(a.portfolio, cfg, a.symbol, a.side, a.qty, a.price, date)
    log_fill(a.state, now, date, a.symbol, a.side, a.qty, a.price)
    print("Recorded %s %s %s at %s on %s in %s. Cash now %s." % (a.side, a.qty, a.symbol.upper(),
                                                                _money(a.price), date, a.portfolio,
                                                                _money(pf["cash"])))
    return 0


def cmd_flatten(a):
    cfg = read_json(a.config, "config", required=False) or {}
    sym = a.symbol.strip().upper()
    now, today = _clock(a)
    source = "Kite, portfolio mode=positions"
    if a.qty is not None:
        qty = _f(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty wants the number of shares you hold, like --qty 8")
    else:
        pf = read_json(a.portfolio, "portfolio", required=False) or {}
        qty = sum(_f(p.get("shares", p.get("qty"))) or 0 for p in pf.get("positions", [])
                  if str(p.get("ticker") or p.get("symbol") or "").upper() == sym)
        source = a.portfolio
        if qty <= 1e-9:
            raise TicketError("nothing to flatten: no %s shares in %s. Check Kite (portfolio mode=positions) "
                              "and pass --qty if you do hold some" % (sym, a.portfolio))
    plan = read_json(a.plan, "plan", required=False) or {}
    flat_by = (plan.get("flat_by") if str(plan.get("symbol", "")).upper() == sym else None) \
        or cfg.get("flat_by") or "15:10"
    order = {"exchange": str(cfg.get("exchange") or "NSE").upper(), "symbol": sym, "side": "sell",
             "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "product": str(cfg.get("product") or "MIS").upper(),
             "why": "flat by %s IST: closes the %s day trade before the close (qty from %s)"
             % (flat_by, sym, source)}
    old = read_json(a.orders, "orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "trader-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "dry_run": dry_run(cfg),
           "note": "Flatten ticket. Nothing is placed until trader-risk passes it and you say yes in the chat.",
           "source": "ticket.py flatten %s on %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Flatten %s: %s (flat by %s IST)." % (sym, plain(order), flat_by))
    print("Wrote it to %s%s." % (a.orders, (" (it replaced %d earlier proposal%s)"
                                             % (replaced, "" if replaced == 1 else "s")) if replaced else ""))
    if a.qty is None:
        print("The qty comes from %s. Check it against Kite (portfolio mode=positions) before you say yes."
              % source)
    gtts = [r.get("gtt_id") for r in state_gtts(a.state, today, sym)]
    print("Next:")
    print("  1. trader-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order.")
    print("  3. FIRST delete the open GTT for %s (gtt mode=list, then mode=delete with its trigger_id%s)." % (
        sym, (", recorded: " + ", ".join(str(g) for g in gtts)) if gtts else ""))
    print("     A GTT left behind can trigger after you are flat and sell shares you no longer hold, a short.")
    print("  4. Then the orders tool with the ticket. Zerodha squares off what is left of an MIS position at")
    print("     about 15:20 anyway, with an extra charge.")
    return 0


def state_gtts(path, today, sym):
    """Today's records for sym that carry a GTT id (from ticket.py result --gtt-id)."""
    st = read_json(path, "broker state", required=False) or {}
    return [r for r in st.get("orders", []) if r.get("gtt_id") and r.get("date") == today
            and str(r.get("symbol", "")).upper() == sym]


def cmd_log(a):
    state = load_state(a.state)
    now, today = _clock(a)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("No decisions recorded%s." % ("" if a.all else " today"))
        return 1
    for r in rows:
        extra = (" id " + r["broker_order_id"]) if r.get("broker_order_id") else ""
        reply = (' reply "%s"' % r["reply"]) if r.get("reply") and r["status"] in ("approved", "declined") else ""
        loss = (" max loss %s" % _money(r["max_loss"])) if r.get("max_loss") is not None and r["status"] == "placed" else ""
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-9s %s%s%s%s" % (r.get("at"), idx, r.get("status"), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d placed%s." % (placed, "" if a.all else " today"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order tickets and your yes (trader-broker). Never places orders.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="pretend it is this IST, e.g. \"2026-10-19 10:15\"")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in IST)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="render the tickets")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="record the user's explicit yes for one order")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word")
    p = sub.add_parser("decline", help="record a no")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("result", help="record what happened after Kite's approval (or a dry run)")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", required=True, choices=["placed", "denied", "failed", "skipped"])
    p.add_argument("--broker-id", help="Kite's order_id for the entry")
    p.add_argument("--gtt-id", help="Kite's trigger_id for the exit GTT")
    p.add_argument("--note")
    p.add_argument("--filled-qty")
    p.add_argument("--filled-price")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("fill", help="record a fill in trader/portfolio.json")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--date", help="YYYY-MM-DD (default: today in IST)")
    p.add_argument("--now")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json")
    p = sub.add_parser("flatten", help="a sell ticket that closes a symbol's position by flat_by")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="shares you hold, from Kite portfolio mode=positions (default: trader/portfolio.json)")
    p.add_argument("--orders", default="trader/orders.json", help="where the ticket is written")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json", help="where GTT ids were recorded")
    clock(p)
    p = sub.add_parser("log", help="today's decisions")
    p.add_argument("--state", default="trader/state/broker.json")
    clock(p)
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
                "fill": cmd_fill, "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)
    except TicketError as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
