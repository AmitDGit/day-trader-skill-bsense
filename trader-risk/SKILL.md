---
name: trader-risk
description: >-
  Risk Manager for NSE day trades on Kite. Checks every order against your
  limits and blocks anything over them before it can reach Kite: a stop is
  required, the loss at the stop plus Zerodha's charges must fit your max
  loss per trade, reward:risk must meet your minimum, the day's risk must
  fit your daily loss limit and trade count, no entries outside 9:30 to
  14:45 IST or on an NSE holiday, prices on the NSE tick, and the stop and
  target inside today's circuit band. Also checks blocked symbols, order
  size, position cap, cash, margin, shorts, F&O and duplicates. Getting out
  is never blocked. Prints PASS or BLOCK with the reason. Use when the user
  says "check my order", "is this safe", "risk check", "can I take this
  trade", "how much have I risked today", or before /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and Kite. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order: it does not go to the user for a yes, and it
does not go to Kite. Most intraday traders lose money. These limits keep
each loss and each day's losses small. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-23 11:40"  # pin the clock (IST)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits (trader-budget ships `config.example.json`) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; with a Kite quote, today's circuit limits |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

Before the check, refresh the price from Kite so the circuit band is known:
Claude calls the Kite connector's `market` tool (`mode=quote`,
`instruments=["NSE:TITAN"]`), saves the answer to
`trader/data/kite-quotes.json`, then runs
`alerts.py quote TITAN --source kite --write`.

## Entries and exits

An **entry** opens or adds to a position: a buy, or a sell that would go
short. An **exit** only reduces what you already hold. Getting out must
always be possible, so an exit is checked for format, asset and short sales
only. Every other rule (day limits, entry window, loss, reward:risk, blocked
list, size, duplicates) turns into a warning for an exit, never a BLOCK.

## The checks

Orders are checked in file order, as if each passed order had filled, so a
batch that is fine order by order but breaks a limit together is caught.

| check | blocks when |
| --- | --- |
| format | no symbol, side not buy or sell, a rupee amount (notional) instead of a share count, an order type Kite does not take, time in force other than `day` or `ioc`, exchange not NSE or BSE, product not MIS or CNC, a limit order with no limit price; a bracket that is not whole shares, not `day`, or misses its stop or target |
| tick | a limit, stop or target price that is not a whole number of NSE ticks for its band |
| asset | a futures or options symbol while `allow_options` is false; anything that is not an NSE or BSE equity symbol |
| short | a sell of more than you hold (`allow_short` false) |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_inr` or over `max_order_inr` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true; a stop on the wrong side of the entry |
| loss | (entries) qty x (entry minus stop), plus the round trip's charges at the stop, over `max_loss_per_trade_inr` |
| reward:risk | (entries) (target minus entry) / (entry minus stop) under `min_reward_risk` |
| circuit | (entries, with a Kite quote) the stop or the target outside today's circuit band, or the price within 1 % of the circuit it is heading for |
| daily loss | (entries) the max losses at the stops of today's entries, plus this one, over `max_daily_loss_inr` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| window | (entries) before `no_entries_before` or after `no_entries_after`, or the market is closed |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

How the numbers work:

- **The entry it measures from**: the limit price for a limit order. For a
  market order, the HIGHER of the plan's entry and a fresh price from
  `trader/prices.json` (under 15 minutes old). An older price is not used,
  and it says so.
- **Charges** are Zerodha's equity intraday charges (see trader-budget), on a
  buy at the entry and a sell at the stop. `"include_costs": false` leaves
  them out.
- **Daily loss** counts the full max loss of every entry placed today, win or
  lose, as trader-broker logged it. Three Rs 500 trades use up a Rs 1,500 day.
- **The window** is IST, worked out in the tool (UTC+05:30, no daylight
  saving), never from the computer's clock zone. Weekends and NSE holidays
  are closed. Set both `no_entries_*` to null to switch the window off.
- **pdt_guard** is a US rule and stays off for NSE.

Warnings do not block, but say them to the user: a LIVE run (`"dry_run":
false`), a `flat_by` at or after Zerodha's MIS square-off (15:20), a CNC
entry on a day trade, a stop that lives only in the plan and not at Kite, a
price too old to use.

## Steps

1. If the price may have moved since the plan, refresh it first (above).
2. Run `check.py`. Exit code 0 means every order passed, 1 means at least one
   was blocked.
3. Tell the user the result in plain words, order by order: the max loss at
   the stop with charges, reward:risk, and how much of today's limits it
   uses. For a BLOCK, give the reason and the fix (fewer shares, a closer
   stop from trader-exit, wait for the window, or skip the trade). Never
   change a limit yourself.
4. If the order changes in any way, run the check again. trader-broker matches
   each order to its verdict by fingerprint, so an edited order is not ready
   until it passes again, and a verdict from yesterday does not count today.

## Example

TITAN, Monday 2026-11-23 at 11:40 IST, the order trader-budget wrote:

```
PASS  #1 buy TITAN 16 shares, entry
          entry 4674.00 (the plan's entry), stop 4650.60, target 4720.80: risk 23.40 a share
          max loss Rs 448.03 (limit Rs 500), reward:risk 2.00 (min 1)
          today before this: 0 of 3 trades, Rs 0 of Rs 1,500 daily loss

1 passed, 0 blocked at 2026-11-23 11:40 IST. Cash after the passed orders: Rs 25,216 (dry run).
```

The same order with 20 shares is blocked: 20 x 23.40 = Rs 468 at the stop,
plus about Rs 88 of charges, is over the Rs 500 limit. A stop of 4,650.63 is
blocked too: under Rs 5,000 the tick is 0.10.

## Rules

- A BLOCK is final for that order. Never talk the user past it, never edit the
  config to make an order pass. The user changes their own limits.
- Always say the reason in plain words.
- Never call an order "safe". A PASS means it fits the user's rules, nothing more.

## What it never does

It never places, approves or changes an order, never raises a limit, and
never treats a PASS as advice to trade.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Dry run by default (`"dry_run": true`): Kite has no paper account, so nothing is sent to Kite until
  the user sets it to false in their own config.
- Nothing in this pack places an order except trader-broker, and only when all of these hold:
  trader-risk passed that exact order today, the user typed an explicit yes for that one order in
  the chat, `"dry_run"` is false, and Kite's own approval (or Claude's Allow once card for the GTT)
  confirms it. Never set the Kite `orders` or `gtt` tool to "Always allow".
- No F&O, margin, short selling or leverage unless the config allows it and the user confirms.
- Kite sign-in happens in Claude's connector settings, never in the chat.
