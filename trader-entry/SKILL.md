---
name: trader-entry
description: >-
  Entry Timer for NSE stocks. Watches a setup bar by bar and tells you the
  moment to get in. Reads Kite candles saved from the Kite connector, or free
  Yahoo 1-minute or 5-minute bars (SYMBOL.NS), builds the opening range (9:15
  to 9:30 IST by default) and calls the entry on the first completed bar
  that CLOSES above the range high, or above a level you give it (like a
  20-day high from the scanner), with an optional volume check. Says waiting
  and how far, triggered with the time and the price, expired, or not open
  yet, and writes trader/entry.json for /trader-exit. Long side only. It never
  places an order. Use when the user says "tell me when to get in", "watch
  TITAN", "has it broken out", "did it break the opening range", "entry
  signal", "time my entry", "check my watchlist", or after /trader-scanner
  and /trader-news, before /trader-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# trader-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. It
reads bars, 1-minute or 5-minute, and waits for each one to finish. A price
that pokes above the high in the middle of a bar is not an entry. A bar that
CLOSES above it is. Then it says the time and the price, writes them down for
the Exit Planner, and stops. It never buys anything. Most intraday traders
lose money, and a clean signal does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TITAN                  # 15-minute opening range, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TITAN --write          # also save trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TITAN --setup level --level 4670
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TITAN --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch TITAN --until 14:45   # one line per closed bar, stops on the trigger
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                   # every hit in trader/watchlist.json
```

Other flags: `--or-minutes N` (default 15), `--json`, `--offline FILE` (Kite
candles saved from the connector, or a saved Yahoo chart, `.json` or
`.json.gz`, or a folder of `<SYMBOL>.json`), `--now "2026-11-23 10:15"` (IST)
to replay a day.

**Kite candles (recommended).** Claude calls the Kite connector's `market`
tool with `mode=search` (`search_mode=get_by_id`, `id=NSE:TITAN`) for the
instrument_token, then `mode=historical`, `interval=5minute`, from today
09:15 to now, and saves the answer as `trader/data/TITAN-5minute.json`. Then
`entry.py check TITAN --offline trader/data/TITAN-5minute.json`. Kite's
candles are Zerodha's own; Yahoo's free bars can lag a few minutes.
`watch` with `--now` or `--offline` runs on a simulated clock and replays the
day bar by bar without waiting.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json` | the scanner's hits (`hits[].symbol`), for `watchlist` |
| `trader/config.json` | `no_entries_before` (09:30) and `no_entries_after` (14:45), IST. Optional |
| `trader/data/<SYMBOL>-5minute.json` | Kite candles Claude saved (with `--offline`) |
| Yahoo chart API | otherwise today's bars for SYMBOL.NS, `range=1d&interval=5m` (or `1m`): free, unofficial, can lag |
| `trader/entry.json` | with `check --write`, or when `watch` triggers: symbol, setup, status, time, bar, price, level, opening range |

## The rule

- **Opening range (orb).** The high and low of the first 15 minutes: the
  9:15, 9:20 and 9:25 five-minute bars, or fifteen 1-minute bars. The level
  to beat is the range high.
- **Level.** A price you give, like a 20-day high from `/trader-scanner`.
- **The trigger** is the first completed bar after the range that CLOSES
  above the level. A wick above is not a trigger. A close exactly at the
  level is not above it.
- **The time** is that bar's close time (the 11:30 bar closes at 11:35 AM).
  The price is its close.
- **Only closed bars count.** A bar is closed when the clock passes its start
  plus 5 (or 1) minutes and the data has caught up to that moment (it waits a
  minute at most). A live tick, like 10:49:45, is never a bar.
- **Volume, if you want it.** `--min-volume-x 1.5` also needs the trigger
  bar's volume at 1.5 times the range bars' average. The 9:15 bar follows
  NSE's 9:00 to 9:08 pre-open auction and is heavy, so 1.0 is already strict.
- **Time limits.** No entries before 9:30 or after 14:45 (config), so the
  trade has time to work before the 15:10 flat-by and Zerodha's MIS
  square-off at about 15:20.
- **What it says.** Waiting (and how far the last close is from the level),
  triggered, expired, or no data. Before 9:15: not open yet. Before 9:30: the
  range is still forming. Weekends and NSE holidays: the market is closed.

## Steps

1. Get the symbol from the user, or run `entry.py watchlist` after
   `/trader-scanner`. Check `/trader-news` for it first.
2. Run `entry.py check SYMBOL`. Tell the user the status in one line:
   waiting and how far, triggered at what time and price, or expired.
3. To wait for it, Claude can run `entry.py watch SYMBOL --until 14:45` in
   the background, or `entry.py check SYMBOL --write` on a `/loop` every 5
   minutes. `watch` wakes just after each bar closes, prints one line per
   bar, and exits 0 on the trigger (it writes `trader/entry.json`) or 1 when
   the setup expires. Keep the computer awake while it watches: a sleeping
   laptop pauses it, and it catches up, late, when it wakes.
4. When it triggers, say the time and the price, and that nothing was placed.
   If the trigger is more than a bar old, say that too: a late entry is a
   different trade.
5. Hand off to `/trader-exit` to set the stop and the target BEFORE anything
   is bought.

## Example

TITAN, Monday 2026-11-23, Kite 5-minute candles (in `tests/fixtures/kite`).
The opening range is 4,615.30 to 4,678.10. At 10:15 it waits:

```
WAITING  last close Rs 4631.50 (10:10 bar), Rs 46.60 under the range high Rs 4678.10 (-1.00%).
```

The first close above the range high came on the 15:05 bar, after the 14:45
cutoff, so at 14:50 the opening-range setup says:

```
EXPIRED  no close above the range high Rs 4678.10 by 14:45, the last time for a new entry.
```

A level setup the same day, `--setup level --level 4670`, triggers on the
11:30 bar: "TRIGGERED 11:35 AM at Rs 4674.00". That is the entry the
`/trader-exit` example plans.

## Rules

- Bar by bar, on Kite candles or free Yahoo 1-minute or 5-minute bars.
  Yahoo's are unofficial and can lag. Say so when a minute matters.
- A signal is information, not an order, and not a promise. Nothing here
  promises winning trades or money.
- Long side only. v2 plans longs only. If the user wants a short, say that.
- One trigger per setup per day: the first close above. Later closes do not
  reset it.
- Never call an entry early because a bar looks like it will close above.

## What it never does

It never places an order, never sizes a position, never sets the stop (that
is `/trader-exit`), never moves the level after the fact, and never counts a
bar that has not closed. It never runs `/trader-broker` from a background
watch: nobody is there to say yes.

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
