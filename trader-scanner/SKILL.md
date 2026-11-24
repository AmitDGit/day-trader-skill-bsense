---
name: trader-scanner
description: >-
  Chart Scanner for NSE stocks. Scans Nifty 100 (or Nifty 50, 200, 500, your
  Kite holdings or your own list) for setups: opening-range breakouts, flags,
  oversold bounces. Builds the symbol list from NSE's index constituents,
  runs a pre-market scan of daily closes (20-day closing-high breakout, bull
  flag, reclaimed the 20-day average, oversold, oversold bounce) and an
  intraday opening-range breakout scan on 5-minute bars (9:15 to 9:30 IST
  range), then writes trader/watchlist.json for trader-news and
  trader-entry. Free Yahoo data (SYMBOL.NS) or Kite candles saved by Claude.
  Use when the user says "scan the market", "scan Nifty", "find me setups",
  "what is breaking out", "opening range breakouts", "oversold stocks",
  "pre-market scan", "build my watchlist", "what should I look at today", or
  at the start of a trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads free charts and
lists the ones that match a rule. That is all it does. A scan is a list of
charts that match a rule, not a list of stocks to buy, and a setup on a chart
is not a prediction. SEBI's own study found that most individual intraday
traders in equity lose money; the scanner does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                       # Nifty 100 -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --index nifty200 --holdings trader/data/kite-holdings.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                          # before the open -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,M&M
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                            # after 9:35 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15                 # cut the clock at 10:15 AM IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --offline trader/data --now "2026-11-23 10:15"   # Kite candles
```

Flags: `--min-price 50` (rupees) and `--min-volume` (daily 1,00,000 shares,
orb 0), `--or-minutes 15`, `--max-confirm 200` (orb stage 2), `--holdings FILE`
to scan your Kite holdings, `--now "2026-11-23 10:15"` (IST) to pin the
clock, `--offline PATH` to read saved files, `--no-write`, `--show N`,
`--json`. Exit code 0 when the scan found something, 1 when it found nothing
or could not run (the reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:45) |
| `trader/data/` | Kite answers Claude saved: `<SYMBOL>-5minute.json` candles, `kite-holdings.json` |

## The universe

`universe` downloads NSE's index constituent list (`ind_nifty100list.csv`
from niftyindices.com, or the same file on archives.nseindia.com) and keeps
the EQ-series symbols. `--index` picks nifty50, nifty100 (default), nifty200
or nifty500. `--holdings FILE` adds every NSE symbol in a saved Kite holdings
answer, and `--add SYMS` adds your own. If the download is blocked, save the
CSV from niftyindices.com and pass `--offline FILE`.

To build `kite-holdings.json`, Claude calls the Kite connector's `portfolio`
tool with `mode=holdings` (read only) and saves the answer there.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request (SYMBOL.NS),
so Nifty 100 takes 5 requests. Liquidity comes from the spark meta: last
price at least `--min-price` and last session's volume at least
`--min-volume`. Run it before 9:15 or after 15:30 IST: during the session the
volume is the day's so far, and today's daily bar is left out until the close.

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Hits are listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:15,
9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar to
CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range (a necessary condition, so no
   breakout is lost).
2. Stage 2, each candidate: the chart with real highs and lows. Range high =
   the highest high of the range bars, range low = the lowest low. At most
   `--max-confirm` (200) are checked, the most traded first; PARTIAL is said
   out loud with the count it skipped.

**With Kite instead of Yahoo.** For a short list (your watchlist), Claude can
fetch today's 5-minute candles with the Kite connector (`market` tool,
`mode=search` for the instrument_token, then `mode=historical`,
`interval=5minute`, from 09:15 today) and save each answer as
`trader/data/<SYMBOL>-5minute.json`. `orb --offline trader/data` reads them.
Kite's candles are Zerodha's own and do not lag like Yahoo's.

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there; a missing bar means a halt or a thin stock. A bar counts only once it
is complete (start + 5 minutes). Before 9:35 AM, on a weekend or NSE
holiday, after the close, or after `no_entries_after` it prints one plain
line and writes nothing.

## Data and limits

- Yahoo's endpoints are free, unofficial and can lag. Kite candles are
  Zerodha's. Bars are 5-minute bars, never tick by tick.
- Partial results are said as partial. Never round a partial scan up to "the whole market".
- NSE equity holidays for 2026 are built in (16 weekdays, from NSE's
  circular). 2027's list is not out yet: the tools say so for 2027 dates.

## Steps

1. Once a month or after an index rebalance: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 AM IST (10:00 to 10:15 is common): `scan.py orb`. Tell the user
   how many usable charts broke their range and when.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL`, then
   `/trader-entry SYMBOL`. Never pick for them.

## Example

Monday 23 November 2026, Kite candles for TITAN and RELIANCE in `tests/fixtures/kite`:

```
python3 scan.py orb --offline tests/fixtures/kite --now "2026-11-23 10:00" --min-price 0
Opening-range breakout scan, Mon 2026-11-23 10:00 AM IST: 15-minute range (9:15 to 9:30 AM), 5-minute bars
No chart closed above its opening-range high by 10:00 AM.
```

TITAN's range was 4,615.30 to 4,678.10. Its first close above came at 15:05
(4,682.00, a hit at 3:10 PM), after the 14:45 entry cutoff, so a live scan
that day would have reported it as too late to trade.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls Yahoo's data real time, and never promises that a setup works.

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
