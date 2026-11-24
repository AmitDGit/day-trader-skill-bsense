---
name: trader-news
description: >-
  News Monitor. Tracks breaking news on every NSE stock you watch or hold and
  flags what moves it: NSE's own corporate filing feeds (announcements,
  board meetings, corporate actions, results), Yahoo Finance India
  headlines, Google News India, and how far each stock is from yesterday's
  close. Shows only what is new since the last check, newest
  first, in IST, tags each item (earnings, board meeting, analyst, deal,
  bonus/split, SEBI, circuit, F&O ban, RBI, FII, macro...) and never repeats
  one. Use when the user says "any news on RELIANCE", "why is this moving",
  "what's the news on my watchlist", "morning briefing", "pre-market news",
  "monitor the news", "did anything break", "any results today", or after
  /trader-scanner finds setups.
argument-hint: "[symbols]"
---

# trader-news

A chart can look perfect and still be about to gap on a results date, a
board meeting, a block deal or a SEBI order. Before a setup becomes a trade,
this skill reads NSE's own filing feeds and two Indian news feeds for every
stock on the watchlist, and tells you only what is new. It also prints how far each stock has moved
today, so a headline and a move sit side by side.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                         # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TITAN --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers MARKSANS="Marksans Pharma" --nse-feeds announcements,board
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-google --no-nse --json
```

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json` | the scanner's hits (trader-scanner) |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| NSE filing RSS (4 feeds, one request each) | `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml`, `Board_Meetings.xml`, `Corporate_action.xml`, `Financial_Results.xml` (`--no-nse` to skip, `--nse-feeds` to pick) |
| `trader/universe.txt` | `SYMBOL|Name` lines from trader-scanner, to match filings by company name |
| Yahoo Finance headline RSS, India | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=TITAN.NS&region=IN&lang=en-IN` |
| Google News RSS, India | `https://news.google.com/rss/search?q=...&hl=en-IN&gl=IN&ceid=IN:en` (`--no-google` to skip) |
| Yahoo Finance chart endpoint | the last price against yesterday's close for `<SYMBOL>.NS` (unofficial, can lag) |
| `trader/state/news.json` | what has been shown (kept 30 days), and company names learned from filings |

**NSE filings.** NSE publishes every company's filings as RSS. The tool
fetches each feed once for all your symbols and keeps a filing when its
file name starts with your symbol (`MARKSANS_23112026181502_...pdf`) or its
company name matches yours. The corporate action and results feeds give the
company name only, so the name comes from `--tickers SYMBOL="Company Name"`,
`trader/universe.txt`, or an earlier filing that carried the symbol (the
tool remembers it). When a symbol shows no filings and you expected some,
pass its name. Filings that can gap a stock (results, board meetings,
dividends, bonus, splits, buybacks, insolvency, regulatory approvals) are
marked `!`. Open the linked PDF before telling the user what it says. If NSE
refuses the request, the check prints a note and the other sources still
run; Claude can then read the feed with its own web fetch. BSE filings are
not covered. For a live price, use a Kite `market` quote instead of the
Yahoo move line.

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story or the exchange filing and read it. Quote the
  source and link it. Never summarise a paywalled story you could not read:
  say so.
- **Exchange filings beat headlines.** NSE filings show with the source
  `NSE filing`. If an NSE or BSE announcement and a
  headline disagree, the filing is what the company told the exchange.
- **Say what it touches.** Every item lists the symbols it touches and its
  tags: earnings, board, analyst, legal (SEBI, NCLT), deal, capital (bonus,
  split, QIP, block deal), people, risk, halt (circuit, F&O ban),
  regulatory (USFDA, RBI), macro (RBI policy, FII flows, GIFT Nifty).
- **MOVING** marks a stock 3 % or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too. A stock near its
  circuit limit can stop trading in one direction.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python3 "${CLAUDE_SKILL_DIR}/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen, `--json` gives everything
   machine readable, `--dry-run` leaves the state alone.
2. Read the items that matter first: every `!` NSE filing, anything tagged
   earnings, board, halt, legal, regulatory or risk, and every MOVING symbol.
3. Write a short brief, per symbol: what happened, the source and link, the
   move, and one line on why it matters to the setup (for example "the board
   meets on results this week: the stock can gap at 9:15, past any stop").
4. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`: a results date, a board meeting, an F&O ban, a block deal.
   Never act on a headline alone.

During the session: `/loop 15m /trader-news`, or a scheduled task each
morning before 9:15 IST.

## Example

The test feeds in `tests/fixtures/news` are synthetic (the links point at
example.com); they show the format. A check on TITAN at 11:40 IST on
2026-11-23:

```
  2026-11-23 11:00 IST  TITAN       Example Mint  Board meeting on dividend next week, says Titan
      tags: board, capital  https://example.com/titan-board
  2026-11-23 08:40 IST  TITAN       Yahoo Finance Titan Company Q2 results: profit rises, jewellery sales strong
      tags: earnings  https://example.com/titan-q2
  2026-11-22 17:30 IST  TITAN       Yahoo Finance Brokerage raises target price on Titan (NSE: TITAN)
      tags: analyst  https://example.com/titan-target
Checked 2026-11-23 11:40 IST. Headlines are leads, not facts; open the story before acting. Not financial advice.
```

The brief would say: results are out and a board meeting is due next week,
so check the NSE announcement before trading TITAN today. When a symbol has
no news, say so rather than padding the brief.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server: one request per feed per symbol, with a pause
  between calls.

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
