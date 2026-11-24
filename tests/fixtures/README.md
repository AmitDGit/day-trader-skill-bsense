# Test fixtures

Real data, as the Kite connector returned it (Zerodha Kite, read 2026-11-24):

- `kite/TITAN-2026-11-23-5minute.json`: TITAN's 5-minute candles on NSE for
  Monday 23 November 2026, `market` tool, `mode=historical`. The answer for
  09:15 to 15:29 ended at the 15:10 candle.
- `kite/RELIANCE-2026-11-23-5minute.json`: RELIANCE, the same day, 09:15 to
  09:55 (nine candles).
- `kite/kite-quotes.json`: RELIANCE, `mode=quote`, read on 24 November 2026
  (an NSE holiday, so it is Monday's close), depth left out.

Sample files, written by hand in the shape of the real thing, not real data:

- `nifty/ind_nifty100list.csv`: an excerpt in the format of niftyindices.com's
  constituent list (ten real constituents with their real ISINs, plus a non-EQ
  row the parser must drop). It is not the full, current Nifty 100.
- `news/*.xml`: headline feeds in the shape of Yahoo Finance and Google News
  RSS. The headlines are made up for the tests.

The Time Machine and the daily scan are tested on generated, seeded sessions
(see the tests), not on market data.

## nse/

`nse-announcements.xml`: the first four items (Centum, Delta Autocorp, Bliss GVS,
DPSC) are copied verbatim from NSE's live Online_announcements.xml feed on
24 November 2026. The Marksans Pharma item is synthetic, written in the same
format. `nse-actions.xml` is synthetic, modelled on NSE's Corporate_action.xml
items (the company name in <title>, no symbol in the link), to test matching by
company name.
