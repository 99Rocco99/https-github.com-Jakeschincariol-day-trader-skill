# The Futures Analyzer skill

A Claude skill that analyzes futures and never trades them. It finds the
contracts you can afford (margin under $4,000 by default), measures how
readable each one moves during the day, and shows what is moving today
compared with a normal day.

It is plain Python with no dependencies, no API key and no signup. It reads
free Yahoo Finance 5-minute futures bars.

This started as a fork of Jake Schincariol's
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT).
Everything that led to an order (entry signals, stops and targets, position
sizing, the risk gate and the broker) has been removed. What is left is
analysis only.

## Install

As a plugin, in Claude Code:

```
/plugin marketplace add 99Rocco99/https-github.com-Jakeschincariol-day-trader-skill
/plugin install futures-analyzer@futures-analyzer
```

Or copy the folder in as a plain skill:

```bash
git clone https://github.com/99Rocco99/https-github.com-Jakeschincariol-day-trader-skill.git
cp -r https-github.com-Jakeschincariol-day-trader-skill/futures-analyzer ~/.claude/skills/
```

Then ask Claude things like "which futures can I afford under $4,000",
"rank the cheap futures", "what's moving today" or "profile micro crude".

## What it does

| command | what you get |
| --- | --- |
| `analyze.py contracts` | all 50 contracts: price, notional, margin (estimated or yours), dollar value of one tick, and whether it fits your cap |
| `analyze.py rank` | the contracts under your cap, ranked by how readable their daily movement has been over the last 60 days |
| `analyze.py today` | each contract's current (or last) session against a normal session at the same time: range used, relative volume, cleanliness, where it sits against yesterday's range |
| `analyze.py profile MCL` | one contract in depth: range percentiles, hour-by-hour share of the movement, weekdays, the last 10 sessions |

The contracts cover micro and full-size stock indexes, crude, natural gas,
metals, currencies, Treasuries, grains, softs, livestock and CME crypto. With
the estimated margins, 31 of them come in under $4,000, including MES, MNQ,
MYM, M2K, MCL, MGC, MHG, M6E, M6B, M6A, MBT, MET, the 10-year micro yield,
6E, 6B, 6J, ZN, ZF, ZT, ZC, ZS, ZW, sugar, lean hogs and live cattle.

### What "readable" means

- **Steady range**: the size of the day's move changes little from day to
  day (a low coefficient of variation).
- **Clean travel**: the open-to-close move is large compared with all the
  back and forth on the way. It is scaled so a random walk scores 1.00.
- **First hour**: how often the rest of the session kept, or reversed, the
  first hour's direction, with a flag when that is no better than a coin flip.
- **Enough ticks and volume**: a range of many ticks on a busy contract.

None of these predicts direction. They describe how the price has moved.

## Example

Live data for Friday 2026-11-06, daytime sessions 2026-08-28 to 2026-11-05.
The top of `rank` (`*` marks an estimated margin):

```
symbol  name                 margin   avg range  ticks  range cv  clean  trend days  after 1st hour  per $1k margin  score
ZM      Soybean Meal         $1,913*       $666     67      0.32   1.17         39%      60% cont ~            $348     58
ZS      Soybeans             $2,986*       $762     61      0.34   1.23         39%       45% rev ~            $255     57
LE      Live Cattle          $3,427*     $1,226    123      0.36   1.19         47%       49% rev ~            $358     56
ZL      Soybean Oil          $2,617*       $646    108      0.34   1.09         41%      50% cont ~            $247     52
MCL     Micro WTI Crude Oil    $813*       $273    273      0.41   1.06         27%      51% cont ~            $335     49
```

Over those 60 days, the grains and cattle had the steadiest, cleanest daily
ranges. The micro stock indexes moved in more erratic sizes: MES had a range
cv of 0.74 and a clean score of 0.97, about the same as a random walk. Only
one contract had a first-hour statistic clearly different from a coin flip
(MYM: the rest of the session reversed the first hour 67 % of the time).

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests run offline on saved Yahoo charts in `tests/fixtures/`.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It cannot see the future, and nothing it prints is a
recommendation to buy or sell.

**Futures are leveraged.** A small move in price is a large move in your
account, in both directions. You can lose more than the margin you put up.

**Margins are estimates unless you enter yours.** Estimated margins (marked
`*`) are notional times a rough rate in `contracts.json`. Exchanges and
brokers change margins often. Put your broker's numbers in
`futures/margins.json` (see `margins.example.json`).

**60 days is a short window.** The statistics describe one recent stretch of
the market. A change of regime can make them stale overnight.

**The data is free and unofficial.** Yahoo Finance's chart endpoint can lag,
change, have gaps or rate-limit you. Cotton's 5-minute bars were too sparse
to use, so cotton is not in the list.

## License

MIT. See `LICENSE`.
