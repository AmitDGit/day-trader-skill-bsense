---
name: trader-broker
description: >-
  Order Executor for Zerodha Kite. Sends approved NSE orders through the Kite
  connector, dry run by default, never without your yes. Shows each order as
  a plain ticket (an MIS entry plus a two-leg GTT for the stop and the
  target, with the max loss at the stop and Zerodha's charges) and the exact
  arguments for the Kite connector's orders and gtt tools, records your yes
  word for word, then Kite's own approval asks again. Builds the sell ticket
  that closes a day trade by your flat-by time (deleting the GTT first),
  records fills, and logs each trade's max loss so trader-risk can hold the
  daily limit. Use when the user says "place the order", "buy it",
  "execute", "send it to Kite", "close my position", "flatten", "get me out",
  "connect Kite", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after these
gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **`"dry_run": false`** in `trader/config.json`, set by the user. Dry run is
   the default: Kite has no paper account, so a dry run shows the calls and
   never makes them.
4. **Kite's own approval** for the entry: the Kite connector's `orders` tool
   asks the user to confirm each placement (a form, or a link to sign in and
   approve in any browser), unless the user turned on "allow future orders"
   there themselves.

The exit GTT is the exception to gate 4: the Kite connector says GTT changes
are outside its order approval. So the user's yes in gate 2 covers the entry
and its GTT together, the ticket shows both before that yes, and the `gtt`
tool is set to "Needs approval" in Claude (Setup, step 3), so Claude's own
Allow once / Deny card stands in for Kite's.

No yes, no order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ORDER_ID --gtt-id TRIGGER_ID
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status skipped --note "dry run"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol TITAN --side buy --qty 16 --price 4674.20
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol TITAN --qty 16
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to Kite. It renders tickets, checks that a reply is a
real yes for that order, builds the flatten ticket, and keeps the log in
`trader/state/broker.json`. `--now "2026-11-23 11:40"` pins the clock (IST).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed, skipped and filled, with each entry's max loss, Kite's order id and the GTT's trigger id |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |
| `trader/config.json` | `dry_run`, `exchange` (NSE), `product` (MIS), `gtt_stop_buffer_pct` |

## Setup: the Kite connector

1. Add Zerodha's Kite connector to Claude (Customize > Connectors) and sign in
   to Kite there, never in the chat. Kite sessions end every morning at about
   6:00 AM IST: if a call says the session expired, ask the user to reconnect.
2. Check it with read-only calls: `portfolio` mode=profile and mode=margins.
3. Tool permissions in Claude (Customize > Connectors > Kite): `orders` and
   `gtt` on **Needs approval**, never Always allow. `alerts` (Kite's own price
   alerts and ATO) on Needs approval too. Read-only tools (`market`,
   `portfolio`, `session`, `help`) can be Always allow.
4. Leave `"dry_run": true` in `trader/config.json` until the user has watched
   a few dry-run tickets and decides, themselves, to set it to false.

## How a ticket maps to Kite

Kite has no bracket order for stocks. So one ticket is two calls:

- **Step 1, the entry**: `orders` with `mode=place`, `variety=regular`,
  `exchange=NSE`, `tradingsymbol`, `transaction_type=BUY`, `quantity`,
  `product=MIS`, `order_type` MARKET or LIMIT (stop orders are SL-M and SL),
  `validity=DAY`, `tag=daytrader`, and `market_protection=-1` on a market order.
- **Step 2, the exit, only after the entry has filled**: `gtt` with
  `mode=place`, `trigger_type=two-leg`, `transaction_type=SELL`, `product=MIS`,
  the stop as `lower_trigger_value` and the target as `upper_trigger_value`,
  both quantities, and `last_price` from `market` mode=ltp right before the
  call. When one leg triggers, Kite places its LIMIT order and cancels the
  other leg. The stop leg's limit sits `gtt_stop_buffer_pct` (0.5 %) under its
  trigger, so a sell limit under the market fills at the best bid; a gap
  through that limit can leave it unfilled.

The ticket prints both argument sets. Send them exactly as printed, with only
`last_price` refreshed. The `why` and the `plan` stay in the file; they are
never sent.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket, both steps, and ask: "Place this order and its GTT? Reply
   yes or no." One order per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order (for example "sure", "yes to all", or a yes that names a different
   stock or amount). Ask again. Never turn a reply into a yes yourself.
4. **Dry run** (the default): do not call Kite. Show what the calls would
   have been, then `ticket.py result --index N --status skipped --note "dry run"`.
5. **Live**: only after "Recorded your yes", call `orders` with exactly the
   printed arguments. If Kite answers `approval_required`, nothing was placed
   yet: share its approval link as a clickable link, then check
   `orders` mode=approval_status with its approval_id once the user says they
   approved. Never repeat the place call, and never approve it for the user.
6. When `orders` mode=history shows the entry COMPLETE, place the GTT with
   `gtt` mode=place (Claude's Allow once card appears).
7. Record it: `ticket.py result --index N --status placed --broker-id <order_id>
   --gtt-id <trigger_id> --filled-qty Q --filled-price P`, or `--status denied`,
   or `--status failed` with `--note`. A failed order is not retried without a
   new check and a new yes. If the entry filled but the GTT failed, say so
   plainly: the position has no stop at Kite, so flatten it, or put a stop in
   through a new ticket (`/trader-risk`, then a yes).

## Steps: while it is open, and out by the close

- trader-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`). The GTT at Kite does the stopping.
- When a GTT leg fills (`gtt` mode=list shows it triggered, `orders` mode=list
  shows the fill), record it: `ticket.py fill --symbol TITAN --side sell --qty 16 --price 4650.40`.
- By `flat_by` (15:10 IST), anything still open gets closed. Zerodha squares
  off MIS positions at about 15:20 itself, with an extra charge, so do not
  wait for it:
  1. Ask Kite how many shares are held: `portfolio` mode=positions (read only).
  2. `ticket.py flatten --symbol TITAN --qty 16` writes a market sell for those
     shares to `trader/orders.json`.
  3. `/trader-risk`. A sell that only closes what the user holds is never
     blocked by the daily limits or the entry window.
  4. `ticket.py show`, then the user's yes for that one order, as above.
  5. **Delete the GTT first** (`gtt` mode=list, then mode=delete with its
     trigger_id, which `result --gtt-id` recorded). A GTT left behind can
     trigger after you are flat and sell shares you no longer hold. Then
     `orders` with the ticket, then `result`.

## Example

```
ORDER 1 of 1, DRY RUN, nothing is sent, Kite (Zerodha)
  BUY 16 TITAN on NSE, market, MIS intraday, good for today
  GTT stop-loss 4650.60
  GTT target 4720.80
  max loss about Rs 374.40 if the stop fills at 4650.60, Rs 448.03 with charges (it can fill worse in a fast market)
  READY: trader-risk PASS, waiting for your yes
  Step 1, the entry: the Kite connector's orders tool with exactly:
    {"mode": "place", "variety": "regular", "exchange": "NSE", "tradingsymbol": "TITAN",
     "transaction_type": "BUY", "quantity": 16, "product": "MIS", "order_type": "MARKET",
     "validity": "DAY", "tag": "daytrader", "market_protection": -1}
  Step 2, the exit, only once the entry has filled: the gtt tool with exactly:
    {"mode": "place", "exchange": "NSE", "tradingsymbol": "TITAN", "transaction_type": "SELL",
     "product": "MIS", "trigger_type": "two-leg", "last_price": 4674,
     "lower_trigger_value": 4650.6, "lower_limit_price": 4627.3, "lower_quantity": 16,
     "upper_trigger_value": 4720.8, "upper_limit_price": 4720.8, "upper_quantity": 16}
```

## What it never does

- Never places an order without every gate, and never two orders on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats Kite passwords, TOTP codes, API keys or access tokens.
- Never switches `"dry_run"` to false. The user does that themselves.
- Never approves a Kite approval link for the user, never repeats an order call that answered
  `approval_required`, and never turns on Kite's "allow future orders".
- Never places F&O, CNC delivery or margin (MTF) orders on its own.
- Never promises a fill price: a market order and a GTT leg fill at whatever the market gives.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Dry run by default (`"dry_run": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all of these hold:
  trader-risk passed that exact order today, the user typed an explicit yes for that one order in
  the chat, `"dry_run"` is false, and Kite's own approval (or Claude's Allow once card for the GTT)
  confirms it. Never set the `orders` or `gtt` tool to "Always allow".
- No F&O, margin, short selling or leverage unless the config allows it and the user confirms.
