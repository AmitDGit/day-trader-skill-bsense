---
name: trader-alerts
description: >-
  Price Alerts. Rings when a price, a stop or the opening bell hits on NSE.
  Turns the trade plan into three alerts in one go (the stop, the target and
  "flat by close" at your flat-by time), plus above / below / stop / target
  levels, percent moves from the previous close, any time of day, and the
  NSE opening bell, each ringing once so you are not spammed. Knows NSE
  hours (9:15 to 15:30 IST) and the 2026 NSE holidays, reads Kite quotes
  saved from the Kite connector (with circuit limits) or free delayed Yahoo
  .NS quotes, and writes trader/prices.json for sizing and the risk check.
  Use when the user says "alert me when", "tell me if RELIANCE hits", "watch
  my stop", "watch my trade", "remind me to close by 3:10", "is the market
  open", "is NSE open today", "when does the market open", "get me a price",
  or right after /trader-exit writes a plan.
argument-hint: "[symbol] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a Kite GTT the stop and the target
already sit at Zerodha and do the work; the alerts tell the user what
happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).
All times are IST.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE open or closed, next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TITAN --stop 4650.6
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TITAN --target 4720.8
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:10 --label "flat by close"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol ITC --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check --source kite            # reads trader/data/kite-quotes.json; exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote TITAN --source kite --write   # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # Kite holdings + portfolio + plan symbols
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset titan-plan-stop
```

`--now "2026-11-23 15:10"` pins the clock (IST); `--offline DIR` reads
saved quote files (`kite-quotes.json` or `yahoo-<SYMBOL>.json`) instead of
the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/data/kite-quotes.json` | the Kite `market` quote answer, saved by Claude |
| `trader/data/kite-holdings.json` | the Kite `portfolio` holdings answer, for `quote --holdings` |
| `trader/prices.json` | the latest quotes and circuit limits, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | other symbols held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the IST clock passed `at` ("15:10") on an NSE trading day | once per trading day |
| `opening_bell` | NSE is open | once per trading day |

A rule with `"date"` is watched on that IST date only; `--from-plan` rules
carry the plan's date, so yesterday's stop never rings today.

## Quotes

- `kite` (preferred): the tool cannot call the Kite connector, so Claude
  calls Kite `market` quote for the symbols (as `NSE:TITAN`, `NSE:RELIANCE`)
  and saves the answer, exactly as it came, to `trader/data/kite-quotes.json`.
  The tool reads `last_price`, the previous close (`ohlc.close`) and the
  circuit limits (`lower_circuit_limit`, `upper_circuit_limit`). trader-risk
  uses the circuits to block an order outside the band.
- `yahoo` (default when no Kite file is given):
  `query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS`, an unofficial free
  JSON endpoint, one request per symbol, half a second apart. It is delayed
  and has no circuit limits.
- Quotes saved here are a snapshot, not a live feed. They are fine for alerts
  and for checking a size, not for timing an order. Kite's price is the one
  that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.

## The NSE clock

Regular session 9:15 to 15:30 IST, Monday to Friday. Pre-open (9:00 to 9:15)
is not traded by this pack. NSE equity holidays for 2026, from the NSE
circular: Jan 15, Jan 26, Mar 3, Mar 26, Mar 31, Apr 3, Apr 14, May 1,
May 28, Jun 26, Sep 14, Oct 2, Oct 20, Nov 10, Nov 24, Dec 25. The 2027 list
is not published yet; for any other year the tool says the holiday list is
unknown. Muhurat trading on Diwali is a separate evening session and is not
covered. IST is a fixed offset (UTC+05:30, no daylight saving), so the tool
needs no time zone files and ignores the computer's own zone.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by
   time (default 15:10, before Zerodha's MIS square-off at about 15:20).
2. While the trade is open, every few minutes (from a Claude scheduled task
   or `/loop`): call Kite `market` quote for today's symbols, save it to
   `trader/data/kite-quotes.json`, then run `check --source kite`. Each run
   rings each alert once. A price can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert means the
   GTT has probably fired: check Kite (`portfolio` positions, `gtt` list) and
   record the fill with trader-broker. "Flat by close" means close anything
   still open: delete the open GTT first, then trader-broker `flatten`, then
   trader-risk, then the user's yes. Never act for them.

## Example

RELIANCE on Monday 2026-11-23, real Kite quote (last price 1351.00, circuit
1215.90 to 1486.10). Alerts: stop 1340, target 1360, flat by close at 15:10.
A `check` at 11:40:

```
NSE OPEN (2026-11-23 11:40 IST, regular session).
Nothing hit. 3 rule(s) watched today, RELIANCE Rs 1351.00.
```

At 15:11:

```
ALERT Flat by close: it is 15:11 IST (set for 15:10), the market closes at 15:30.
An alert is information, not an order. The GTT's stop and target already sit at Kite: check Kite
(portfolio mode=positions, gtt mode=list) and record any fill (ticket.py fill). To close a position
yourself: ticket.py flatten, then trader-risk and your yes.
```

It rings once. And `clock` on Tuesday 2026-11-24:

```
IST 2026-11-24 10:00 (Tuesday): NSE closed, NSE holiday: Prakash Gurpurb Sri Guru Nanak Dev.
Next open: 2026-11-25 09:15 IST.
```

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a saved quote as live.
- Confirm every new rule back to the user: symbol, type, level, day.

## What it never does

It never places, cancels or changes an order or a GTT, never claims a quote
is live, and never predicts where a price is going.

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
