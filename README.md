# The Day Trader skill, NSE and Kite edition

9 Claude skills for intraday trading on NSE and BSE with Zerodha Kite: scan
the Nifty charts, track Indian market news, time every entry and exit, and
replay every outcome before you risk a rupee.

This is an Indian-market adaptation of
[Jake Schincariol's Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT). The method is the same: scan, entry trigger, fixed stop and target,
Time Machine backtest, sizing, risk checks, and your explicit yes before
every order. What changed is the market around it:

- **NSE clock.** 9:15 to 15:30 IST, entries 9:30 to 14:45, flat by 15:10
  (before Zerodha's MIS square-off at about 15:20), NSE 2026 holidays.
- **Kite data.** Claude reads quotes, 5-minute candles and holdings from the
  Kite connector and saves them to `trader/data/`; the Python tools read
  those files. Yahoo Finance `.NS` symbols are the fallback.
- **Nifty universe.** Nifty 50 / 100 / 200 / 500 lists from niftyindices.com,
  plus your Kite holdings.
- **Rupees and Indian rules.** NSE tick sizes, circuit limits, Zerodha's
  intraday charges (brokerage, STT, exchange, SEBI, GST, stamp duty) in every
  max-loss figure.
- **Kite tickets.** An MIS entry through Kite `orders`, then a two-leg GTT
  (stop and target, one cancels the other). Dry run by default.
- **Indian news.** Yahoo Finance India and Google News India, tagged for
  results, board meetings, SEBI, circuits, F&O ban, RBI and FII flows.

The US-only skills (the SEC earnings analyst and the Congress trade tracker)
were removed.

Nothing in this pack can place an order on its own, and dry run is the
default: Kite has no paper account, so until you set `"dry_run": false` the
broker skill shows the exact Kite calls and sends nothing.

## Install

Paste this into Claude:

```
https://github.com/AmitDGit/day-trader-skill-bsense

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add AmitDGit/day-trader-skill-bsense
/plugin install day-trader-skill-nse@day-trader-skill-bsense
```

Or copy the folders for plain `/trader-scanner` commands:

```bash
git clone https://github.com/AmitDGit/day-trader-skill-bsense.git
cp -r day-trader-skill-bsense/trader-* ~/.claude/skills/
```

The tools need Python 3.8 or newer. Nothing to pip install.

### Connect Kite

Add the Kite (Zerodha) connector in Claude and sign in there, never in the
chat. Then, in Customize > Connectors > tool permissions, set the Kite
`orders` and `gtt` tools to **Needs approval**, never "Always allow". GTT
changes are outside Kite's own order approval, so Claude's Allow once card
is the second check for them.

## The nine

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans the Nifty 100 (or 50 / 200 / 500) and your holdings for setups: opening-range breakouts, 20-day highs, oversold bounces. |
| `/trader-news` | News Monitor | Tracks Indian market news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup candle by candle and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target on the NSE tick before you enter. |
| `/trader-timemachine` | Time Machine | Replays the rest of the session 10,000 times from the stock's own last 60 days, plus every past time the setup fired. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade, Zerodha charges included. |
| `/trader-risk` | Risk Manager | Checks every order against your limits, the tick size and the circuit band, and stops anything over them. |
| `/trader-broker` | Order Executor | Builds the Kite MIS order and the two-leg GTT, dry run by default, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop, the opening bell or your flat-by time hits. |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 15:10                                           (while it is open)
news                                                                          (on a schedule)
```

An example on real Kite candles: TITAN, Monday 23 November 2026.

1. **`/trader-scanner`** finds TITAN in the Nifty 100 with a level to watch
   at 4670.
2. **`/trader-news`** checks the morning's TITAN headlines in IST before
   anything else.
3. **`/trader-entry`** watched TITAN candle by candle on the 5-minute Kite
   candles. The 11:30 candle closed above 4670: triggered at 11:35 AM, entry
   4674.0.
4. **`/trader-exit`** set the plan: stop 0.5 % under the entry, rounded down
   to the 0.10 tick, 4650.6 (23.4 a share at risk); target 2R, 4720.8; flat
   by 15:10 either way.
5. **`/trader-timemachine`** replays the rest of the day 10,000 times from
   TITAN's own last 60 days of candles (seed 19, so anyone can repeat it) and
   re-runs the same rule on those real sessions. Its verdict is one honest
   line: coin flip, leans one way, or strongly one way.
6. **`/trader-budget`** with a Rs 1,00,000 budget, a Rs 80,000 position cap
   and a Rs 500 max loss per trade: 16 shares (Rs 74,784). If the stop fills
   at 4650.6, the loss is Rs 374.40 plus Rs 73.63 in Zerodha charges, Rs
   448.03 in all. At the target, the gain is Rs 748.80 less Rs 73.95 in
   charges, Rs 674.85.
7. **`/trader-risk`** checks it: max loss with charges, daily loss limit,
   trades per day, reward to risk, the entry window, tick size, circuit band,
   position size and cash. PASS or BLOCK, with the reason.
8. **`/trader-broker`** shows the ticket in plain words: step 1, buy 16 TITAN
   MIS through Kite `orders`; step 2, after the fill, a two-leg GTT with the
   stop at 4650.6 (limit 4627.3) and the target at 4720.8. You type yes for
   that exact order. In dry run it stops there and sends nothing.
9. **`/trader-alerts`** rings on the stop, the target and at 15:10 to
   flatten whatever is still open (delete the GTT first).

## The tools

All standard-library Python. Claude saves Kite connector answers to
`trader/data/`, and the tools read them with `--offline` or `--source kite`.

```bash
python3 trader-scanner/scan.py universe --index nifty100 --holdings trader/data/kite-holdings.json
python3 trader-scanner/scan.py orb --at 09:45                          # opening-range breakouts so far
python3 trader-news/news.py --tickers TITAN --hours 12                 # headlines and today's move
python3 trader-entry/entry.py check TITAN --setup level --level 4670 --offline trader/data/TITAN-5minute.json
python3 trader-exit/exit.py plan --stop pct:0.5 --write                # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --offline trader/data/TITAN-5minute.json --until 15:10 --write
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the Kite tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by close
python3 trader-alerts/alerts.py check --source kite                    # rings what hit, once
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline. The TITAN and RELIANCE candles, the RELIANCE quote
with its circuit limits and the Nifty 100 constituents are real data read
from Kite on 23 to 24 November 2026; the Time Machine sessions and the news
feeds are generated and labelled as such (`tests/fixtures/README.md`).

## Fine print

**Not financial advice.** This is software that reads market data and does
arithmetic. It does not know your situation and it cannot see the future.
SEBI's own studies show most individual intraday traders lose money. Decide
for yourself, and talk to a SEBI-registered adviser if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order, you type yes
for it in the chat, `"dry_run"` is false, and Kite's approval (or Claude's
Allow once card for the GTT) confirms it. No F&O, margin, short selling or
leverage unless you turn them on.

**MIS square-off.** Zerodha squares off open MIS positions at about 15:20
and charges for it. The pack's flat-by time is 15:10 so you close first.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute candles. Results, board meetings, RBI
policy and circuits can do things those 60 days never did.

**A stop is a plan, not a guarantee.** A gap or a circuit can fill a stop
well past its price, or not at all. The max loss shown is the loss at the
stop price plus charges.

**Charges.** Zerodha intraday equity charges as published on
zerodha.com/charges (read 24 November 2026); they live in
`trader-budget/config.example.json` so you can update them.

**Taxes.** Intraday gains are speculative business income in India. Nothing
here is tax advice.

## Files

```
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
tests/              unittest suite + offline fixtures
```

MIT. Original pack by [Jake Schincariol](https://opusjake.ai); NSE and Kite
adaptation by AmitDGit.
