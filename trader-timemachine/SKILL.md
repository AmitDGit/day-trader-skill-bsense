---
name: trader-timemachine
description: >-
  Time Machine. Replays every possible outcome of a trade before you risk a
  rupee: 10,000 simulated sessions plus every past time the setup fired.
  Takes the plan from trader-exit (entry, stop, target), rebuilds the rest of
  the day 10,000 times from the stock's own 5-minute Kite candles over the last 60
  days, and re-runs the same rule on every past session. Prints the odds of
  target first, stop first, or neither by the close, where the price sits at
  the close, the average R, the history, and one honest verdict, then hands
  off to /trader-budget. Use when the user says "run the time machine",
  "replay this trade", "what are the odds", "simulate this trade", "monte
  carlo", "backtest this setup", "how often does this hit the target", "is
  this a coin flip", or after /trader-exit writes a plan, before
  /trader-budget.
argument-hint: "[path to plan.json, or TICKER]"
---

# trader-timemachine

The Time Machine sits between the plan and the money. trader-exit has set
the entry, the stop and the target. Before anything is sized or sent, this
skill asks one question: if today plays out like the stock's own last 60
days on NSE, how often does this plan hit the target first, the stop first,
or neither? It answers with 10,000 replays and with the real record of the
same rule on every past session. It is a simulation built from the stock's
own recent candles, not a prediction. Intraday trading loses most people
money (SEBI's own studies say so), and a good-looking replay does not
change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).
All times are IST.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                    # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # also save trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:10      # end each replay at your flat-by time
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --offline trader/data/TITAN-5minute.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol TITAN --date 2026-11-23 \
    --entry 4674.0 --stop 4650.6 --target 4720.8 --entry-time "11:35 AM" --stop-rule pct
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from           # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (default 19), `--window N` (default 2
bars), `--json`, `--now "2026-11-23 11:40"` (IST) to pin the clock.

## Getting 60 days of candles

The tool cannot call the Kite connector itself. Claude fetches the candles
and saves them, then the tool reads the file:

1. Kite `market` historical data for the symbol, interval `5minute`, from 60
   calendar days back to today. Save the answer as it came to
   `trader/data/<SYMBOL>-5minute.json` (the `{"data": [...]}` candles).
2. Run with `--offline trader/data/<SYMBOL>-5minute.json`.

Without `--offline` the tool falls back to Yahoo (`<SYMBOL>.NS`, `range=60d`,
`interval=5m`), which is free, unofficial and can lag. Kite is the better
source when the connector is signed in.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the plan from trader-exit: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, target_r, opening range |
| `trader/data/<SYMBOL>-5minute.json` | 60 days of 5-minute Kite candles (or a saved Yahoo chart) |
| `trader/timemachine.json` | with `--write`: `{plan, mc, history}` plus the verdict. `mc` holds the odds, percentiles, the fan-chart bands, 160 sample paths and a 24-bin histogram of the close |

## How it works

1. **The pool.** It keeps only FULL sessions before the plan's date: all 75
   five-minute bars, 9:15 to 15:30 IST. Muhurat sessions, gaps and today
   are left out. Every bar becomes four ratios to the bar before it:
   open, high, low and close over the previous close.
2. **One replay.** Start at the entry price. For each bar left in the day,
   pick a past bar from the same time of day (plus or minus 2 bars) at
   random, and scale it to the current price. Bar by bar, it checks the stop
   first, then the target. A bar that touches both counts as the stop.
3. **10,000 replays** give four odds. Target first. Stop first. Neither,
   which means the trade was still open at `--until` (default 15:30, the
   close). Green, which means target first or above the entry at `--until`.
   R is +1 at a 1R target, -1 at the stop, and otherwise the distance from
   the entry at `--until` divided by the risk. A gap through the stop still
   counts as -1R here. A real fill can be worse, and a stock that hits its
   circuit may not fill at all.
4. **The history.** The plan's own rule (the same opening range, stop rule
   and target R) runs again on every one of those past sessions. That is
   what really happened, not a simulation.
5. **The verdict** is one line from the numbers. It looks only at the
   replays that hit one side, and asks how often the target came first. A
   bigger target needs to win less often to break even: 1 in (1 + R). That
   is 50 % at 1R, 33 % at 2R, 25 % at 3R. Less than 5 points from break-even:
   "Close to a coin flip" at 1R, "Close to break-even" at any other R. 5 to
   15 points: "Leans toward the target" or "Leans toward the stop". 15 or
   more: "Strongly toward" one of them. Zerodha's charges are not in the R;
   trader-budget adds them.
6. **Below the verdict**, when it applies: a line when more than 40 % of the
   replays hit neither (the price at `--until` decides those), and the
   average R when its sign goes against the lean.

**The seed.** The draws come from Python's `random.Random(seed)`, seed 19 by
default. Same plan, same data, same seed: the same numbers, on any machine.
Say the seed with every result so the user can repeat it.

**5-minute candles only.** It refuses, in one plain line, when there are
fewer than 20 full sessions, when the entry bar is not in the data (wrong
date, not closed yet, a future day), or when the plan does not make sense (a
stop above a buy's entry, an entry off the 5-minute grid). A live
in-progress candle is never used.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/trader-exit`. If there
   is none, run that first, or pass the plan as flags.
2. Fetch and save 60 days of 5-minute Kite candles (above).
3. Run `timemachine.py run --offline <file> --write --until 15:10` (or the
   config's `flat_by`), so "neither" means still open at the time you would
   get out, before Zerodha's MIS square-off.
4. Tell the user, in this order: the four odds, the median and the 5 to 95
   range of the price at `--until`, the average R, the history line, then the
   verdict line and any line under it exactly as printed. Say the seed.
5. If the verdict is a coin flip, close to break-even or leans toward the
   stop, say so plainly. Do not dress it up. If the history and the replays
   disagree, say that too.
6. Say once that this is built from the last 60 days and is not a
   prediction. Results, board meetings, RBI policy, block deals and F&O ban
   news can do things those 60 days never did. Check `/trader-news` for the
   stock before going on.
7. If the user still wants the trade, hand off to `/trader-budget` to size it.

## Example: the reel

This run uses generated candles (a seeded random walk in Kite's candle
shape, the same generator as `tests/test_timemachine.py`), so the numbers
show the format, not a real stock. Plan: buy DEMO at 949.20 at 11:10 AM,
stop 944.40, target 958.80 (2R), flat by 15:10.

```
10,000 replays of the rest of the session, 11:10 AM to 3:10 PM (48 five-minute bars), seed 19.
  target first   26.8 %
  stop first     71.8 %
  neither        1.4 %    still open at 3:10 PM
  green          27.8 %   target first, or above the entry at 3:10 PM
  Price at 3:10 PM: median 948.18, 90 % of replays between 927.03 and 969.37.
  Average R: -0.176
History: the same rule on each of those 40 real sessions fired 30 times:
11 target, 18 stop, 1 neither. Average R +0.153.
Leans toward the stop: at 2R the target has to come first in 33 % of the
replays that hit one side; it did in 27 %.
```

The replays lean toward the stop while the history was slightly positive.
Both of those are what the user should hear, side by side, before
`/trader-budget` sizes anything.

## Rules

- Every number comes from the run. Never round a coin flip up into an edge.
- The verdict line and the lines under it are printed by the tool. Repeat
  them, do not rewrite them. Never judge a 2R or 3R plan by target first vs
  stop first alone: the verdict already weighs the target's R.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Candles are 5-minute candles, checked bar by bar, never tick by tick and
  never real time.
- Always say the seed, so any run can be repeated.
- One plan per run. A changed entry, stop, target or date is a new run.

## What it never does

It never places an order, never sizes a position, never changes the plan,
and never calls a result a sure thing. It never prints a P&L or a profit.
It never uses a candle that has not closed yet, and never mixes today's
candles into the pool.

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
