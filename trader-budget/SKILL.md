---
name: trader-budget
description: >-
  Budget Manager for NSE day trades in rupees. Sizes every position to your
  budget and your max loss per trade, with Zerodha's intraday charges
  (brokerage, STT, exchange fees, SEBI fee, GST, stamp duty) counted in the
  loss. Reads the trade plan from trader-exit (entry, stop, target), finds
  the whole shares that fit inside four limits (max loss per trade, position
  cap, max order, cash after your buffer), says which limit decided it, and
  writes ONE order to trader/orders.json: an MIS entry with the stop and the
  target for a two-leg GTT. A stop too far away for your max loss is a plain
  refusal, not a smaller order. Nothing is placed. Use when the user says
  "how many shares", "size this trade", "how much should I buy", "I have
  1 lakh", "I only want to risk Rs 500 a trade", "set my rules", "keep 10%
  in cash", or after /trader-exit writes a plan.
argument-hint: "[budget in rupees]"
---

# trader-budget

The Budget Manager turns a plan ("buy TITAN at 4,674, stop 4,650.60") into an
exact order ("buy 16 shares"), inside rules the user sets once. The stop
decides the size: the further away the stop, the fewer shares. It writes a
proposal only. trader-risk checks it and trader-broker asks the user yes or
no. Most intraday traders lose money. Sizing to a max loss keeps each loss
small; it does not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write        # a limit order at the plan's entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 4672.50 --json # a limit order at 4,672.50
python3 "${CLAUDE_SKILL_DIR}/size.py" --targets targets.example.json --budget 100000 --config split.json   # weights mode
```

`--now "2026-11-23 11:40"` pins the clock (IST). A plan for another day is
refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, setup, flat-by time (trader-exit writes it) |
| `trader/prices.json` | optional: a fresh price above the plan's entry means a bigger risk (trader-alerts writes it) |
| `trader/portfolio.json` | optional: its cash caps the size (trader-broker keeps it) |
| `trader/orders.json` | the one proposed order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words. All
money is in rupees, all times IST:

- **budget**: how much money this is for (default example Rs 1,00,000). Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade_inr**: the most one trade may lose if the stop fills at the stop, charges
  included (default Rs 500).
- **max_position_pct**, **max_order_inr**, **min_order_inr**: the biggest position (75 % of the
  budget), the biggest order (Rs 80,000) and the smallest order (Rs 500).
- The day limits trader-risk enforces: **max_daily_loss_inr** (Rs 1,500), **max_trades_per_day** (3),
  **min_reward_risk** (1.0), **require_stop** (true), **no_entries_before** / **no_entries_after**
  ("09:30" / "14:45") and **flat_by** ("15:10", before Zerodha's MIS square-off at about 15:20).
- **include_costs** (true) and **costs**: Zerodha's equity intraday charges, from zerodha.com/charges
  (read 2026-11-24): brokerage 0.03 % or Rs 20 an executed order, whichever is lower; STT 0.025 % on
  the sell side; NSE transaction charges 0.00307 %; SEBI Rs 10 a crore; GST 18 % on brokerage,
  transaction and SEBI charges; stamp duty 0.003 % on the buy side. Update them when Zerodha does.
- **exchange** ("NSE") and **product** ("MIS", intraday).
- **blocked**: symbols they never want to trade.
- Keep **dry_run** true until they have watched it work on a few tickets.

MIS leverage: Zerodha lets MIS positions use margin (about 5x on many
stocks). This pack sizes on cash only (`"allow_margin": false`), so a loss
can never be bigger than the money set aside for it.

## Step 2: size the trade

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write
```

Whole shares only. The size is the smallest of four limits:

| limit | shares |
| --- | --- |
| max loss | the most shares where shares x (entry minus stop) plus the round trip's charges at the stop stays within `max_loss_per_trade_inr` |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_inr` / entry |
| cash | (budget minus the cash buffer) / entry, never more than the cash in `trader/portfolio.json` |

The entry it sizes at: the limit price with `--limit`. For a market order, the
plan's entry, or the price in `trader/prices.json` if it is fresh (under 15
minutes old) and higher. A price that ran up since the plan means a bigger
loss at the same stop, so fewer shares. A lower price never shrinks the risk.

It refuses, and writes no order, when: the size is zero shares, the order is
under the minimum, reward:risk is under `min_reward_risk`, the stop is not
below the entry, the target is not above it (the move already happened), the
plan is for another day, the symbol is blocked, or the plan is a short. Say
the reason to the user in one line.

## Step 3: show the user

Show the four limits, which one decided the size, the shares, the rupees,
the max loss at the stop, and the charges (net loss at the stop, net gain at
the target). Say plainly that a stop is an order, not a promise: in a fast
market it can fill below the stop. Then hand over to `/trader-risk`.

## Example

TITAN on Monday 2026-11-23: entry 4,674.00 at 11:35 AM, stop 4,650.60, target
4,720.80 (2R). Risk 23.40 a share. The example config: Rs 1,00,000 budget,
10 % cash buffer, Rs 500 max loss.

| limit | the math | shares |
| --- | --- | --- |
| max loss | Rs 500 / 23.40 = 21, less charges: 18 x 23.40 = Rs 421.20 plus about Rs 77 | 18 |
| position cap | 75 % of Rs 1,00,000 = Rs 75,000 / 4,674 | **16 (decides it)** |
| max order | Rs 80,000 / 4,674 | 17 |
| cash | Rs 1,00,000 minus Rs 10,000 = Rs 90,000 / 4,674 | 19 |

16 shares = Rs 74,784. Max loss at the stop: 16 x 23.40 = Rs 374.40, plus
about Rs 73.63 of charges = Rs 448.03. It writes:

```json
{"exchange": "NSE", "symbol": "TITAN", "side": "buy", "qty": "16", "type": "market",
 "time_in_force": "day", "product": "MIS", "order_class": "bracket",
 "take_profit_limit_price": "4720.80", "stop_loss_stop_price": "4650.60",
 "why": "level on TITAN: 16 shares, bound by your position cap (16 x 23.40 = Rs 374.40 at the stop)",
 "plan": {"entry": 4674.0, "stop": 4650.6, "target": 4720.8, "risk_per_share": 23.4, "max_loss": 374.4,
          "costs_at_stop": 73.63, "net_loss_at_stop": 448.03, "setup": "level", "entry_time": "11:35 AM",
          "flat_by": "15:10"}}
```

"bracket" here means an entry plus a stop and a target; trader-broker turns
it into a Kite MIS order and a two-leg GTT. `why` and `plan` are notes for
trader-risk and trader-broker and are never sent to Kite.

## Weights mode (kept from v1)

`--weights RELIANCE=30,HDFCBANK=25` or `--targets FILE` (`targets.example.json`
here, an example split, not a recommendation) splits a budget across a list
by weight: the cash buffer comes off the top, weights are renormalised to
100, any stock over `max_position_pct` is pinned at the cap and its excess
shared out, and slices under the minimum order are dropped. Kite takes whole
shares only, so use `--whole-shares --prices trader/prices.json`; a rupee
amount without a share count is blocked by trader-risk. These orders are CNC
(delivery) buys with no stop: trader-risk blocks them while `require_stop` is
true. Use a separate config (`--config`) for a long-term split.

## Rules

- Proposals only. This skill never calls a Kite tool.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan or the prices. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.
- Free Yahoo prices are unofficial and can lag. Kite's price is the one that fills.

## What it never does

It never places, approves or schedules an order, never raises a limit on its
own, never shrinks a stop to fit more shares, and never sizes F&O, margin or
short positions.

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
