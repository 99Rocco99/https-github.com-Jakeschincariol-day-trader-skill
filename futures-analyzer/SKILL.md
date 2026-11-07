---
name: futures-analyzer
description: >-
  Futures Analyzer. Pure analysis, no trading: finds the futures contracts you
  can afford (estimated or your real margin under a cap, $4,000 by default)
  and measures how readable each one moves during the day, from 60 days of
  free Yahoo 5-minute bars. Ranks them by how steady the size of the daily
  move is, how cleanly it travels (versus a random walk), how often the rest
  of the session follows or fades the first hour, its size in ticks and its
  volume. Shows what each contract is doing in today's session compared with
  a normal session at the same time (range used, relative volume,
  cleanliness, position against yesterday's range), and profiles one
  contract hour by hour and by weekday. Never places, sizes or signals a
  trade. Use when the user says "which futures can I afford", "cheap
  futures", "futures under $4,000", "what moves predictably", "rank the
  futures", "what's moving today", "is crude trending", "profile MES",
  "best hours to watch gold", "micro futures", or "analyze futures".
argument-hint: "[contracts|rank|today|profile SYMBOL] [--max-margin 4000]"
---

# futures-analyzer

The Futures Analyzer describes how futures contracts move. It does not tell
anyone to buy or sell, it does not size positions and it has no connection
to a broker. It answers two questions:

1. **Which contracts can I afford to hold, and which of those move in the
   most readable way?** (`contracts`, `rank`, `profile`)
2. **What is moving today, compared with a normal day?** (`today`)

"Readable" means the size of the daily move is steady from day to day and
the price travels in straighter lines than a random walk. That is not the
same as knowing the direction. No statistic here predicts which way the
next move goes, and the tool says so when a number is no better than a coin
flip. Most people who trade futures lose money: leverage makes every move
bigger in both directions.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/analyze.py" contracts                    # every contract: price, notional, margin, tick value
python3 "${CLAUDE_SKILL_DIR}/analyze.py" rank                         # contracts under $4,000 margin, ranked
python3 "${CLAUDE_SKILL_DIR}/analyze.py" rank --max-margin 2000 --micros
python3 "${CLAUDE_SKILL_DIR}/analyze.py" today                        # the current (or last) session vs a normal one
python3 "${CLAUDE_SKILL_DIR}/analyze.py" today --sort relvol          # busiest first (also: range, clean, score)
python3 "${CLAUDE_SKILL_DIR}/analyze.py" profile MCL                  # one contract in depth
python3 "${CLAUDE_SKILL_DIR}/analyze.py" rank --session globex        # the full 6 PM to 5 PM session instead of daytime
```

Common flags: `--max-margin N` (default 4000), `--symbols MES,MCL` (named
contracts, ignores the cap), `--micros`, `--session rth|globex` (default
rth), `--margins FILE`, `--json`, `--offline DIR` (saved Yahoo chart files
named `SYMBOL.json` or `SYMBOL.json.gz`), `--now "2026-11-06 11:30"` (New
York time), `--refresh`, `--max-age MINUTES` (cache, default 10),
`--cache DIR`.

## What it reads and writes

| file | what |
| --- | --- |
| `contracts.json` (this folder) | 50 contracts: Yahoo symbol, dollars per point, tick size, an estimated margin rate, the daytime session in New York time |
| `futures/margins.json` | optional: your broker's real margins, `{"MES": 2300, "MCL": 900}`. These replace the estimates |
| Yahoo spark API | last prices for every contract, 20 a request |
| Yahoo chart API | 60 days of 5-minute bars, one request a contract (free, unofficial, can lag) |
| `futures/cache/` | the charts it fetched, reused for 10 minutes |

## Margin: "under $4,000 to enter"

- Without `futures/margins.json`, margin is **estimated** as notional times
  the contract's `margin_pct` (about 6.5 % for stock indexes, 2 to 3.5 % for
  currencies, 35 % for bitcoin). These are rough. Exchanges change margins
  often, and every margin shown with a `*` is an estimate.
- Ask the user for their broker's real numbers and write them to
  `futures/margins.json`. A real number always wins.
- Brokers often allow much lower **day-trade** margins (sometimes $50 to $500
  for a micro). Holding past the close needs the full amount. The cap here
  is the full amount, so a contract under it can also be held overnight.
- The margin is not the most you can lose. A futures loss can be bigger than
  the margin.

## How `rank` works

For each contract under the cap it takes every **full** session in the last
60 days, leaving out today. A full session has at least 80 % of the usual
number of bars, so half days and data gaps drop out. `rth` uses each
contract's daytime hours from `contracts.json` (stock indexes 9:30 to 4:00,
crude 9:00 to 2:30, grains 9:30 to 2:20 and so on, New York time). `globex`
uses the CME trading day, 6:00 PM to 5:00 PM.

| column | meaning |
| --- | --- |
| avg range | the average high-to-low move of one session, in dollars for one contract |
| ticks | that range in ticks. Small numbers mean the spread and commissions eat a bigger share |
| range cv | standard deviation of the daily range / its average. Lower = the size of the day's move is steadier |
| clean | net open-to-close move / the total distance travelled bar to bar, times the square root of the bar count. A random walk scores about 1.00 at any session length. Above 1 = straighter travel, below = more back and forth |
| trend days | sessions whose open-to-close move was at least 60 % of the day's range |
| after 1st hour | how often the rest of the session kept the first hour's direction (cont) or reversed it (rev). `~` means not clearly different from 50 % (within 1.96 standard errors) |
| per $1k margin | the average range divided by the margin, per $1,000 |
| volume/day | Yahoo's volume for the session |
| score | 0 to 100. Consistency (cv 0.8 to 0.2) 30, cleanliness (clean 0.9 to 1.4) 30, first-hour edge beyond one standard error 20, size (20 to 200 ticks) 10, volume (500 to 50,000) 10 |

The score is a summary of these descriptions, not a quality rating and not a
recommendation. Show the columns, not just the score.

## How `today` works

It takes the latest session in the data. While it is still going, the line
says `live` and the time of the last completed bar. When the session is
over, or on a weekend, it says `closed` and the date. It compares the
session with the full sessions before it **at the same number of bars**:

- **range vs usual**: today's range so far / the average range after the same number of bars.
- **rel vol**: volume so far / the average volume after the same number of bars.
- **of avg day**: today's range so far as a share of a whole normal session.
- **clean now / usual**: today's cleanliness so far against its usual.
- **where**: above the prior session's high, below its low, or inside.
- **IN PLAY**: relative volume at least 1.2x AND cleaner than usual. That
  means busy and travelling, nothing more.
- When the first hour is done and the contract's first-hour statistic is
  clearly not a coin flip, it prints that fact once.

## How `profile` works

One contract: the range in dollars and ticks with the 10th to 90th
percentile, movement per $1,000 of margin, cleanliness, the first-hour
statistic with its sample size, the lag-1 autocorrelation of 5-minute
returns (above 0 leans momentum, below 0 leans mean reversion, and it says
whether it is big enough to rely on), each hour's share of the movement and
how often it rose, each weekday, and the last 10 sessions.

## Steps

1. Run `contracts` once and show the user which contracts fit under their
   cap. Ask whether they know their broker's margins; if so, write
   `futures/margins.json` and run it again.
2. Run `rank`. Show the table, then explain the top few in plain words: how
   big a normal day is in dollars for one contract, how steady that size is,
   and how clean. Point out the ones whose ticks are small (costs matter more)
   or whose volume is thin.
3. During the session, run `today` to see what is busier and cleaner than
   usual. Say whether each line is `live` or `closed`.
4. For a contract the user cares about, run `profile SYMBOL` and tell them
   which hours carry most of the movement.
5. Repeat after a week or two. Sixty days is a short window: a regime change
   (an election, a war, an OPEC meeting, a Fed surprise) can change all of
   these numbers.

## Rules

- Analysis only. Never say "buy", "sell", "go long", "short it", "enter" or
  "a good trade". Say "moves", "ranges", "travels", "matched".
- Every number comes from the bars, `contracts.json` or the user's margins.
- Always say when a margin is estimated.
- Never call the data real time. Yahoo's free bars are unofficial and can lag.
- Say the sample: how many sessions and which dates.
- When a statistic carries `~` or "not clearly different from a coin flip",
  say so plainly.
- Never print a P&L or a projected return. A range is not a profit.

## What it never does

It never places, sizes, approves or schedules an order, never picks a
direction, never gives entry or exit levels, and never connects to a broker.

## Safety

- Education and analysis, not financial advice.
- Futures are leveraged: a loss can be larger than the margin put up.
- Margins shown with `*` are estimates. The broker's number is the real one.
- Free Yahoo data is unofficial, can lag and sometimes has gaps (cotton's
  5-minute bars were too sparse to use, so it is not in the list).
