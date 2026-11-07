#!/usr/bin/env python3
"""futures-analyzer: which cheap futures move in a steady, readable way, and what is moving today.

Pure analysis. It reads free Yahoo Finance 5-minute futures bars and prints statistics.
It never places, sizes or signals a trade.

  analyze.py contracts                  every contract, its price, notional and estimated margin
  analyze.py rank                       contracts under --max-margin, ranked by how readable they move
  analyze.py today                      what each contract is doing in the current (or last) session
  analyze.py profile MES                one contract in depth: hours, weekdays, ranges, recent days

Common flags: --max-margin 4000, --session rth|globex, --symbols MES,MCL, --json,
--offline DIR (saved Yahoo chart files, SYMBOL.json or SYMBOL.json.gz), --now "2026-11-06 11:00"
(New York time), --margins FILE, --refresh, --cache DIR.
"""

import argparse
import datetime as dt
import gzip
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_FILE = os.path.join(HERE, "contracts.json")
BAR = 300  # seconds in a 5-minute bar
UA = "Mozilla/5.0 (futures-analyzer)"
HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------- time (New York, no tz database needed)

def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def et_offset_hours(utc):
    """-4 during US daylight saving time, else -5. utc is a naive UTC datetime."""
    y = utc.year
    start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7))   # 2:00 EST = 7:00 UTC
    end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6))    # 2:00 EDT = 6:00 UTC
    return -4 if start <= utc < end else -5


def to_et(ts):
    utc = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=ts)
    return utc + dt.timedelta(hours=et_offset_hours(utc))


def et_to_ts(local):
    """New York wall time (naive) to a unix timestamp."""
    for off in (-4, -5):
        utc = local - dt.timedelta(hours=off)
        if et_offset_hours(utc) == off:
            return int((utc - dt.datetime(1970, 1, 1)).total_seconds())
    return int((local + dt.timedelta(hours=5) - dt.datetime(1970, 1, 1)).total_seconds())


def now_ts(args):
    if getattr(args, "now", None):
        return et_to_ts(dt.datetime.strptime(args.now, "%Y-%m-%d %H:%M"))
    return int(time.time())


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def fmt_hm(minutes):
    h, m = divmod(int(minutes), 60)
    suffix = "AM" if h < 12 else "PM"
    return "%d:%02d %s" % ((h - 1) % 12 + 1, m, suffix)


# ---------------------------------------------------------------- contracts and margins

def load_contracts():
    with open(CONTRACTS_FILE, encoding="utf-8") as fh:
        return json.load(fh)["contracts"]


def load_margins(path):
    """Real margins the user typed in, {"MES": 2300, ...}. Missing file: no overrides."""
    if path is None:
        path = os.path.join("futures", "margins.json")
        if not os.path.exists(path):
            return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {k.upper(): float(v) for k, v in data.items() if not k.startswith("_") and v is not None}


def margin_for(contract, price, overrides):
    """(margin in dollars, 'set' or 'est')."""
    sym = contract["symbol"]
    if sym in overrides:
        return overrides[sym], "set"
    if price is None:
        return None, "est"
    return round(price * contract["point_value"] * contract["margin_pct"]), "est"


# ---------------------------------------------------------------- data

def _get(url, tries=2):
    last = None
    for host in HOSTS:
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url.replace("{host}", host), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429 and attempt == 0:
                    time.sleep(5)
                    continue
                break
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last = e
                break
    raise RuntimeError("Yahoo did not answer (%s)" % last)


def _read_json(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _offline_file(folder, sym):
    for name in (sym + ".json", sym + ".json.gz", sym + "=F.json", sym + "=F.json.gz"):
        p = os.path.join(folder, name)
        if os.path.exists(p):
            return p
    return None


def fetch_chart(sym, args):
    """Raw Yahoo chart JSON, 60 days of 5-minute bars. Cached for --max-age minutes."""
    if args.offline:
        p = _offline_file(args.offline, sym)
        if not p:
            raise RuntimeError("no saved chart for %s in %s" % (sym, args.offline))
        return _read_json(p)
    cache = os.path.join(args.cache, sym + "-5m.json")
    if not args.refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < args.max_age * 60:
        return _read_json(cache)
    data = _get("https://{host}/v8/finance/chart/%s=F?range=60d&interval=5m&includePrePost=true" % sym)
    try:
        os.makedirs(args.cache, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass
    time.sleep(0.3)
    return data


def fetch_prices(contracts, args):
    """{symbol: last price}. Offline: from the saved charts. Online: Yahoo spark, 20 a request."""
    out = {}
    if args.offline:
        for c in contracts:
            p = _offline_file(args.offline, c["symbol"])
            if p:
                out[c["symbol"]] = chart_meta(_read_json(p)).get("regularMarketPrice")
        return out
    syms = [c["symbol"] for c in contracts]
    for i in range(0, len(syms), 20):
        chunk = ",".join(s + "=F" for s in syms[i:i + 20])
        data = _get("https://{host}/v7/finance/spark?symbols=%s&range=1d&interval=1d" % chunk)
        for r in (data.get("spark") or {}).get("result") or []:
            resp = (r.get("response") or [{}])[0]
            price = (resp.get("meta") or {}).get("regularMarketPrice")
            if price is not None:
                out[r["symbol"].replace("=F", "")] = price
        time.sleep(0.3)
    return out


def chart_meta(data):
    res = ((data or {}).get("chart") or {}).get("result") or []
    return res[0].get("meta", {}) if res else {}


def parse_bars(data, now):
    """Completed 5-minute bars, nulls and the live tick dropped: [(ts, o, h, l, c, v)]."""
    res = ((data or {}).get("chart") or {}).get("result") or []
    if not res:
        return []
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    bars = []
    for i, t in enumerate(ts):
        if t % BAR or t + BAR > now:
            continue
        try:
            row = (t, o[i], h[i], l[i], c[i], v[i] or 0)
        except IndexError:
            continue
        if None in row[1:5]:
            continue
        bars.append(row)
    return bars


# ---------------------------------------------------------------- sessions

def trading_date(et_dt):
    """CME trading day: 6:00 PM New York starts the next day's session."""
    return (et_dt + dt.timedelta(hours=6)).date()


def split_sessions(bars, contract, session):
    """{date: [bars]} for the chosen session. rth uses the contract's daytime window."""
    out = {}
    a, b = (hm(x) for x in contract["rth"])
    for bar in bars:
        e = to_et(bar[0])
        if session == "rth":
            mins = e.hour * 60 + e.minute
            if a <= mins < b and e.weekday() < 5:
                out.setdefault(e.date(), []).append(bar)
        else:
            d = trading_date(e)
            if d.weekday() < 5:
                out.setdefault(d, []).append(bar)
    return out


def session_start_minute(contract, session):
    return hm(contract["rth"][0]) if session == "rth" else 18 * 60


# ---------------------------------------------------------------- one session's numbers

def day_stats(bars):
    o = bars[0][1]
    c = bars[-1][4]
    hi = max(b[2] for b in bars)
    lo = min(b[3] for b in bars)
    path, prev = 0.0, o
    for b in bars:
        path += abs(b[4] - prev)
        prev = b[4]
    rng = hi - lo
    fh = bars[min(11, len(bars) - 1)][4]  # close of the 12th bar: the first hour
    return {
        "open": o, "high": hi, "low": lo, "close": c, "range": rng,
        "net": c - o,
        "efficiency": abs(c - o) / path if path > 0 else 0.0,
        # efficiency x sqrt(bars): about 1.0 for a random walk whatever the session length
        "clean": (abs(c - o) / path) * math.sqrt(len(bars)) if path > 0 else 0.0,
        "trend_day": rng > 0 and abs(c - o) >= 0.6 * rng,
        "close_loc": (c - lo) / rng if rng > 0 else 0.5,
        "first_hour": fh - o,
        "rest_of_day": c - fh,
        "volume": sum(b[5] for b in bars),
        "bars": len(bars),
    }


def sign(x):
    return (x > 0) - (x < 0)


# ---------------------------------------------------------------- the whole sample

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def full_sessions(sessions, before=None):
    """Sessions with at least 80 % of the usual bar count (drops half days and data gaps)."""
    days = sorted(d for d in sessions if before is None or d < before)
    if not days:
        return []
    usual = statistics.median(len(sessions[d]) for d in days)
    return [d for d in days if len(sessions[d]) >= 0.8 * usual and len(sessions[d]) >= 12]


def analyse(contract, bars, session, margin, before=None):
    """Every statistic for one contract over the full sessions before `before` (a date)."""
    sessions = split_sessions(bars, contract, session)
    days = full_sessions(sessions, before)
    if len(days) < 10:
        return None
    pv, tick = contract["point_value"], contract["tick"]
    stats = [day_stats(sessions[d]) for d in days]
    ranges = [s["range"] for s in stats]
    usd = [r * pv for r in ranges]
    mean_r = statistics.mean(ranges)
    cv = statistics.pstdev(ranges) / mean_r if mean_r else 1.0
    eff = statistics.mean(s["efficiency"] for s in stats)
    clean = statistics.mean(s["clean"] for s in stats)

    # after the first hour: does the rest of the session keep going the same way?
    pairs = [(sign(s["first_hour"]), sign(s["rest_of_day"])) for s in stats]
    pairs = [p for p in pairs if p[0] and p[1]]
    n_ft = len(pairs)
    cont = sum(1 for a, b in pairs if a == b) / n_ft if n_ft else 0.5
    se = math.sqrt(0.25 / n_ft) if n_ft else 1.0

    # lag-1 autocorrelation of 5-minute returns inside each session
    xs, ys = [], []
    for d in days:
        cl = [b[4] for b in sessions[d]]
        rets = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl)) if cl[i - 1]]
        xs += rets[:-1]
        ys += rets[1:]
    ac = _corr(xs, ys)

    vol = statistics.mean(s["volume"] for s in stats)
    ticks = mean_r / tick if tick else 0.0

    consistency = clamp((0.8 - cv) / 0.6)
    cleanliness = clamp((clean - 0.9) / 0.5)
    edge = clamp((abs(cont - 0.5) - se) / 0.2)
    size = clamp(math.log10(max(ticks, 1) / 20)) if ticks else 0.0
    liquidity = clamp(math.log10(max(vol, 1) / 500) / 2)
    score = 100 * (0.30 * consistency + 0.30 * cleanliness + 0.20 * edge + 0.10 * size + 0.10 * liquidity)

    return {
        "symbol": contract["symbol"], "name": contract["name"], "group": contract["group"],
        "session": session, "sessions": len(days), "first": days[0].isoformat(), "last": days[-1].isoformat(),
        "margin": margin,
        "avg_range": mean_r, "avg_range_usd": statistics.mean(usd), "median_range_usd": statistics.median(usd),
        "p10_range_usd": _pct(usd, 10), "p90_range_usd": _pct(usd, 90),
        "avg_range_ticks": ticks,
        "range_cv": cv,
        "efficiency": eff, "clean": clean,
        "trend_days": sum(s["trend_day"] for s in stats) / len(stats),
        "continuation": cont, "continuation_n": n_ft, "continuation_se": se,
        "continuation_clear": abs(cont - 0.5) > 1.96 * se,
        "autocorr": ac, "autocorr_n": len(xs),
        "autocorr_clear": abs(ac) > 1.96 / math.sqrt(len(xs)) if xs else False,
        "avg_volume": vol,
        "range_per_1k_margin": statistics.mean(usd) / margin * 1000 if margin else None,
        "score": round(score, 1),
        "parts": {"consistency": consistency, "cleanliness": cleanliness, "edge": edge,
                  "size": size, "liquidity": liquidity},
        "_days": days, "_stats": stats, "_sessions": sessions,
    }


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def _pct(values, p):
    v = sorted(values)
    if not v:
        return 0.0
    k = (len(v) - 1) * p / 100
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


# ---------------------------------------------------------------- today

def today_report(contract, bars, session, margin, now):
    """The latest session (in progress or the last one), compared with the full sessions before it."""
    sessions = split_sessions(bars, contract, session)
    if not sessions:
        return None
    cur_day = max(sessions)
    hist = analyse(contract, bars, session, margin, before=cur_day)
    if hist is None:
        return None
    cur = sessions[cur_day]
    s = day_stats(cur)
    pv = contract["point_value"]
    prior_day = hist["_days"][-1]
    prior = day_stats(hist["_sessions"][prior_day])

    # in progress? the session's end has not passed yet
    start = session_start_minute(contract, session)
    if session == "rth":
        end_ts = et_to_ts(dt.datetime.combine(cur_day, dt.time(0)) + dt.timedelta(minutes=hm(contract["rth"][1])))
    else:
        end_ts = et_to_ts(dt.datetime.combine(cur_day, dt.time(17)))
    live = now < end_ts

    k = len(cur)
    # what a normal session had done after the same number of bars
    by_now_range, by_now_vol = [], []
    for d in hist["_days"]:
        sb = hist["_sessions"][d][:k]
        by_now_range.append(max(b[2] for b in sb) - min(b[3] for b in sb))
        by_now_vol.append(sum(b[5] for b in sb))
    typical_range_now = statistics.mean(by_now_range)
    typical_vol_now = statistics.mean(by_now_vol)

    last = cur[-1][4]
    if last > prior["high"]:
        where = "above the prior session's high"
    elif last < prior["low"]:
        where = "below the prior session's low"
    else:
        where = "inside the prior session's range"

    first_hour_done = k >= 12
    fh_dir = sign(s["first_hour"]) if first_hour_done else 0

    out = {
        "symbol": contract["symbol"], "name": contract["name"], "session": session,
        "date": cur_day.isoformat(), "live": live, "bars": k,
        "as_of": to_et(cur[-1][0] + BAR).strftime("%Y-%m-%d %H:%M"),
        "last": last, "open": s["open"],
        "change_vs_prior_close_pct": (last / prior["close"] - 1) * 100 if prior["close"] else 0.0,
        "move_from_open_usd": s["net"] * pv,
        "range_usd": s["range"] * pv,
        "avg_day_range_usd": hist["avg_range_usd"],
        "pct_of_avg_day_range": s["range"] / hist["avg_range"] * 100 if hist["avg_range"] else 0.0,
        "range_vs_usual_by_now": s["range"] / typical_range_now if typical_range_now else 0.0,
        "room_left_usd": max(0.0, hist["avg_range"] - s["range"]) * pv,
        "clean": s["clean"], "usual_clean": hist["clean"],
        "direction": {1: "up", -1: "down", 0: "flat"}[sign(s["net"])],
        "where": where,
        "relative_volume": s["volume"] / typical_vol_now if typical_vol_now else None,
        "first_hour": {1: "up", -1: "down", 0: "not done" if not first_hour_done else "flat"}[fh_dir],
        "continuation": hist["continuation"], "continuation_clear": hist["continuation_clear"],
        "score": hist["score"], "margin": margin,
    }
    out["in_play"] = bool(out["relative_volume"] and out["relative_volume"] >= 1.2
                          and s["clean"] >= hist["clean"])
    return out


# ---------------------------------------------------------------- printing

def money(x):
    if x is None:
        return "-"
    return "${:,.0f}".format(x)


def pct(x, digits=0):
    return ("{:.%df}%%" % digits).format(x * 100)


def table(rows, header, left=2):
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    lines = ["  ".join(str(h).ljust(w) for h, w in zip(header, widths)).rstrip()]
    for r in rows:
        lines.append("  ".join(str(c).ljust(w) if i < left else str(c).rjust(w)
                               for i, (c, w) in enumerate(zip(r, widths))).rstrip())
    return "\n".join(lines)


def pick(args, contracts, prices, overrides):
    """Contracts the user asked for, under the margin cap unless named with --symbols."""
    named = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    out = []
    for c in contracts:
        if named and c["symbol"] not in named:
            continue
        if args.micros and not c["micro"]:
            continue
        m, kind = margin_for(c, prices.get(c["symbol"]), overrides)
        if not named and (m is None or m > args.max_margin):
            continue
        out.append((c, m, kind))
    if named:
        missing = set(named) - {c["symbol"] for c, _, _ in out}
        if missing:
            print("Not in contracts.json: %s" % ", ".join(sorted(missing)), file=sys.stderr)
    return out


def cmd_contracts(args):
    contracts = load_contracts()
    overrides = load_margins(args.margins)
    prices = fetch_prices(contracts, args)
    rows, data = [], []
    for c in contracts:
        p = prices.get(c["symbol"])
        m, kind = margin_for(c, p, overrides)
        notional = p * c["point_value"] if p is not None else None
        ok = m is not None and m <= args.max_margin
        data.append({"symbol": c["symbol"], "name": c["name"], "group": c["group"], "price": p,
                     "notional": notional, "margin": m, "margin_source": kind,
                     "tick_value": c["tick"] * c["point_value"], "under_budget": ok})
        rows.append([c["symbol"], c["name"], c["group"], "-" if p is None else "{:g}".format(p),
                     money(notional), money(m) + ("" if kind == "set" else "*"),
                     "${:,.2f}".format(c["tick"] * c["point_value"]), "yes" if ok else "no"])
    if args.json:
        return _dump(data)
    print(table(rows, ["symbol", "name", "group", "price", "notional", "margin", "tick", "<= %s" % money(args.max_margin)]))
    n = sum(1 for d in data if d["under_budget"])
    print("\n%d of %d contracts are at or under %s margin." % (n, len(data), money(args.max_margin)))
    print("* estimated from notional (margin_pct in contracts.json). Put your broker's real numbers in "
          "futures/margins.json; exchanges change margins often. Brokers' intraday margins can be far lower, "
          "overnight margin is the full amount.")
    return 0


def _load_all(args, chosen, now):
    results = []
    failed = []
    for c, m, kind in chosen:
        try:
            bars = parse_bars(fetch_chart(c["symbol"], args), now)
        except RuntimeError as e:
            failed.append("%s (%s)" % (c["symbol"], e))
            continue
        results.append((c, m, kind, bars))
    return results, failed


def cmd_rank(args):
    now = now_ts(args)
    contracts = load_contracts()
    overrides = load_margins(args.margins)
    prices = fetch_prices(contracts, args)
    chosen = pick(args, contracts, prices, overrides)
    if not chosen:
        print("No contract fits under %s margin." % money(args.max_margin))
        return 1
    loaded, failed = _load_all(args, chosen, now)
    today = to_et(now).date()
    res = []
    for c, m, kind, bars in loaded:
        a = analyse(c, bars, args.session, m, before=today)
        if a is None:
            failed.append("%s (fewer than 10 full sessions)" % c["symbol"])
            continue
        a["margin_source"] = kind
        res.append(a)
    res.sort(key=lambda a: -a["score"])
    if args.json:
        return _dump([_public(a) for a in res] + ([{"failed": failed}] if failed else []))
    if not res:
        print("No usable data. " + "; ".join(failed))
        return 1
    rows = []
    for a in res:
        cont = "%s %s" % (pct(a["continuation"]), "cont" if a["continuation"] >= 0.5 else "rev")
        if not a["continuation_clear"]:
            cont += " ~"
        rows.append([a["symbol"], a["name"], money(a["margin"]) + ("" if a["margin_source"] == "set" else "*"),
                     money(a["avg_range_usd"]), "%.0f" % a["avg_range_ticks"], "%.2f" % a["range_cv"],
                     "%.2f" % a["clean"], pct(a["trend_days"]), cont,
                     money(a["range_per_1k_margin"]), "{:,.0f}".format(a["avg_volume"]), "%.0f" % a["score"]])
    print("%s session, full sessions %s to %s, 5-minute bars (Yahoo, free, can lag)." % (
        "Daytime (rth)" if args.session == "rth" else "Full Globex", min(a["first"] for a in res), max(a["last"] for a in res)))
    print(table(rows, ["symbol", "name", "margin", "avg range", "ticks", "range cv", "clean", "trend days",
                       "after 1st hour", "per $1k margin", "volume/day", "score"]))
    print("""
How to read it:
  avg range   the usual high-to-low move of one session, in dollars for ONE contract.
  range cv    how much that size changes day to day. Lower = the size of the day's move is more predictable.
  clean       how straight the session travels, scaled so 1.00 is a random walk. Above 1 = straighter, below = choppier.
  trend days  sessions whose open-to-close move was at least 60% of the day's high-to-low range.
  after 1st hour  how often the rest of the session kept going the same way as the first hour (cont) or reversed (rev).
              ~ = not clearly different from a coin flip with this many days.
  per $1k margin  the average range divided by the margin: how much a normal day moves per $1,000 put up.
  score       0-100: consistency 30, cleanliness 30, first-hour edge 20, size in ticks 10, volume 10.
* estimated margin. These are descriptions of the last ~60 days, not forecasts of direction.""")
    if failed:
        print("Skipped: " + "; ".join(failed))
    return 0


def cmd_today(args):
    now = now_ts(args)
    contracts = load_contracts()
    overrides = load_margins(args.margins)
    prices = fetch_prices(contracts, args)
    chosen = pick(args, contracts, prices, overrides)
    if not chosen:
        print("No contract fits under %s margin." % money(args.max_margin))
        return 1
    loaded, failed = _load_all(args, chosen, now)
    reps = []
    for c, m, kind, bars in loaded:
        r = today_report(c, bars, args.session, m, now)
        if r is None:
            failed.append("%s (not enough data)" % c["symbol"])
            continue
        reps.append(r)
    key = {"score": lambda r: -r["score"], "relvol": lambda r: -(r["relative_volume"] or 0),
           "range": lambda r: -r["range_vs_usual_by_now"], "clean": lambda r: -r["clean"]}[args.sort]
    reps.sort(key=key)
    if args.json:
        return _dump(reps + ([{"failed": failed}] if failed else []))
    if not reps:
        print("No usable data. " + "; ".join(failed))
        return 1
    stamp = to_et(now).strftime("%a %Y-%m-%d %H:%M")
    print("%s New York. %s session. Each line compares the session with the same point of a normal session." % (
        stamp, "Daytime (rth)" if args.session == "rth" else "Full Globex"))
    rows = []
    for r in reps:
        state = ("live %s" % r["as_of"][11:]) if r["live"] else ("closed %s" % r["date"][5:])
        rows.append([r["symbol"], r["name"], state, "{:+.2f}%".format(r["change_vs_prior_close_pct"]),
                     money(r["range_usd"]), "%.0f%%" % r["pct_of_avg_day_range"],
                     "%.1fx" % r["range_vs_usual_by_now"],
                     "-" if r["relative_volume"] is None else "%.1fx" % r["relative_volume"],
                     "%.2f / %.2f" % (r["clean"], r["usual_clean"]), r["direction"],
                     r["where"].replace("the prior session's ", "prior ").replace(" range", ""),
                     "IN PLAY" if r["in_play"] else ""])
    print(table(rows, ["symbol", "name", "session", "vs prior", "range", "of avg day", "range vs usual",
                       "rel vol", "clean now/usual", "dir", "where", ""]))
    hot = [r for r in reps if r["in_play"]]
    print()
    if hot:
        print("Busier AND cleaner than usual:")
        for r in hot:
            left = ("about %s of a normal day's range left" % money(r["room_left_usd"]) if r["room_left_usd"] > 0
                    else "already past its normal day's range")
            print("  %s %s: %.1fx volume, %.0f%% of its average day's range used, %s." % (
                r["symbol"], r["direction"], r["relative_volume"], r["pct_of_avg_day_range"], left))
    else:
        print("Nothing is both busier and cleaner than usual right now.")
    for r in reps:
        if r["first_hour"] in ("up", "down") and r["continuation_clear"]:
            print("%s: first hour went %s; over the sample the rest of the session %s %s of the time." % (
                r["symbol"], r["first_hour"], "kept going" if r["continuation"] >= 0.5 else "reversed",
                pct(max(r["continuation"], 1 - r["continuation"]))))
    if any(not r["live"] for r in reps):
        print("Sessions marked closed are the last completed session, not today.")
    print("Description, not prediction: unusual volume and clean movement can stop at any bar.")
    if failed:
        print("Skipped: " + "; ".join(failed))
    return 0


def cmd_profile(args):
    now = now_ts(args)
    contracts = {c["symbol"]: c for c in load_contracts()}
    sym = args.symbol.upper()
    if sym not in contracts:
        print("%s is not in contracts.json. Known: %s" % (sym, ", ".join(sorted(contracts))))
        return 1
    c = contracts[sym]
    overrides = load_margins(args.margins)
    data = fetch_chart(sym, args)
    price = chart_meta(data).get("regularMarketPrice")
    m, kind = margin_for(c, price, overrides)
    bars = parse_bars(data, now)
    a = analyse(c, bars, args.session, m, before=to_et(now).date())
    if a is None:
        print("Fewer than 10 full sessions of %s in the data." % sym)
        return 1
    pv = c["point_value"]

    # hour by hour, from the session start
    start = session_start_minute(c, args.session)
    hours = {}
    for d in a["_days"]:
        for b in a["_sessions"][d]:
            e = to_et(b[0])
            mins = (e.hour * 60 + e.minute - start) % (24 * 60)
            hours.setdefault(mins // 60, []).append(b)
    hour_rows = []
    total_move = 0.0
    hour_data = []
    for h in sorted(hours):
        bs = hours[h]
        per_day = {}
        for b in bs:
            per_day.setdefault(to_et(b[0]).date(), []).append(b)
        rng = statistics.mean(max(x[2] for x in v) - min(x[3] for x in v) for v in per_day.values())
        net = [v[-1][4] - v[0][1] for v in per_day.values()]
        up = sum(1 for x in net if x > 0) / len(net)
        vol = statistics.mean(sum(x[5] for x in v) for v in per_day.values())
        hour_data.append({"start": fmt_hm(start + h * 60), "avg_range_usd": rng * pv, "up_share": up,
                          "avg_volume": vol})
        total_move += rng
    for hd in hour_data:
        hd["share_of_hourly_movement"] = hd["avg_range_usd"] / (total_move * pv) if total_move else 0
        hour_rows.append([hd["start"], money(hd["avg_range_usd"]), pct(hd["share_of_hourly_movement"]),
                          pct(hd["up_share"]), "{:,.0f}".format(hd["avg_volume"])])

    # weekday
    wd = {}
    for d, s in zip(a["_days"], a["_stats"]):
        wd.setdefault(d.weekday(), []).append(s)
    wd_data = [{"day": WEEKDAYS[k], "sessions": len(v), "avg_range_usd": statistics.mean(x["range"] for x in v) * pv,
                "clean": statistics.mean(x["clean"] for x in v)} for k, v in sorted(wd.items())]

    recent = []
    for d, s in list(zip(a["_days"], a["_stats"]))[-10:]:
        recent.append({"date": d.isoformat(), "day": WEEKDAYS[d.weekday()], "range_usd": s["range"] * pv,
                       "net_usd": s["net"] * pv, "clean": s["clean"],
                       "first_hour": {1: "up", -1: "down", 0: "flat"}[sign(s["first_hour"])],
                       "rest": {1: "up", -1: "down", 0: "flat"}[sign(s["rest_of_day"])]})

    if args.json:
        out = _public(a)
        out.update({"margin_source": kind, "hours": hour_data, "weekdays": wd_data, "recent": recent})
        return _dump(out)

    print("%s  %s  (%s), %s session, %d full sessions %s to %s" % (
        sym, c["name"], c["group"], args.session, a["sessions"], a["first"], a["last"]))
    print("Price %s, one contract = %s notional, margin %s%s, one tick = $%.2f." % (
        "-" if price is None else "{:g}".format(price), money(price * pv if price else None), money(m),
        "" if kind == "set" else " (estimated)", c["tick"] * pv))
    print()
    print("Session range: average %s (%.0f ticks), median %s, 80%% of days between %s and %s. Range cv %.2f." % (
        money(a["avg_range_usd"]), a["avg_range_ticks"], money(a["median_range_usd"]), money(a["p10_range_usd"]),
        money(a["p90_range_usd"]), a["range_cv"]))
    if a["range_per_1k_margin"]:
        print("That is %s of movement per $1,000 of margin on a normal day." % money(a["range_per_1k_margin"]))
    print("Cleanliness %.2f (1.00 = random walk), trend days %s." % (a["clean"], pct(a["trend_days"])))
    print("After the first hour, the rest of the session %s %s of %d days (%s)." % (
        "continued" if a["continuation"] >= 0.5 else "reversed", pct(max(a["continuation"], 1 - a["continuation"])),
        a["continuation_n"], "clearly not a coin flip" if a["continuation_clear"] else "not clearly different from a coin flip"))
    print("5-minute bars: lag-1 autocorrelation %+.3f (%s; %s)." % (
        a["autocorr"], "momentum" if a["autocorr"] > 0 else "mean reversion",
        "clear" if a["autocorr_clear"] else "too small to rely on"))
    print("Score %.0f of 100 (consistency %.2f, cleanliness %.2f, first-hour edge %.2f, size %.2f, volume %.2f)." % (
        a["score"], *[a["parts"][k] for k in ("consistency", "cleanliness", "edge", "size", "liquidity")]))
    print("\nHour by hour (New York time, start of each hour of the session):")
    print(table(hour_rows,
                ["hour", "avg range", "share", "up hours", "volume"], left=1))
    print("\nBy weekday:")
    print(table([[w["day"], str(w["sessions"]), money(w["avg_range_usd"]), "%.2f" % w["clean"]] for w in wd_data],
                ["day", "sessions", "avg range", "clean"], left=1))
    print("\nLast 10 full sessions:")
    print(table([[r["date"], r["day"], money(r["range_usd"]), "{:+,.0f}".format(r["net_usd"]),
                  "%.2f" % r["clean"], r["first_hour"], r["rest"]] for r in recent],
                ["date", "day", "range", "net $", "clean", "1st hour", "rest"]))
    print("\nDollar figures are for one contract. A description of the last ~60 days, not a forecast.")
    return 0


def _public(a):
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in a.items() if not k.startswith("_")}


def _dump(obj):
    print(json.dumps(obj, indent=2, default=str))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--max-margin", type=float, default=4000, help="margin cap in dollars (default 4000)")
        p.add_argument("--session", choices=["rth", "globex"], default="rth",
                       help="rth: the contract's daytime session (default); globex: 6 PM to 5 PM New York")
        p.add_argument("--symbols", help="comma list, e.g. MES,MCL (ignores the margin cap)")
        p.add_argument("--micros", action="store_true", help="micro contracts only")
        p.add_argument("--margins", help="JSON of real margins, {\"MES\": 2300}. Default futures/margins.json if present")
        p.add_argument("--offline", help="folder of saved Yahoo chart files")
        p.add_argument("--cache", default=os.path.join("futures", "cache"))
        p.add_argument("--max-age", type=float, default=10, help="minutes a cached chart stays fresh")
        p.add_argument("--refresh", action="store_true", help="ignore the cache")
        p.add_argument("--now", help='pin the clock, New York time, "YYYY-MM-DD HH:MM"')
        p.add_argument("--json", action="store_true")
        return p

    common(sub.add_parser("contracts", help="every contract with price, notional and margin"))
    common(sub.add_parser("rank", help="rank contracts under the margin cap"))
    t = common(sub.add_parser("today", help="what each contract is doing now"))
    t.add_argument("--sort", choices=["score", "relvol", "range", "clean"], default="score")
    p = common(sub.add_parser("profile", help="one contract in depth"))
    p.add_argument("symbol")

    args = ap.parse_args(argv)
    try:
        return {"contracts": cmd_contracts, "rank": cmd_rank, "today": cmd_today, "profile": cmd_profile}[args.cmd](args)
    except RuntimeError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
