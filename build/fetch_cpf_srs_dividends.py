#!/usr/bin/env python3
"""One-time backfill of CPF / SRS cash dividends -> data/cpf-srs-dividends.csv.

CPF-IS and SRS holdings have their own transaction files (cpf-stocks, srs-stocks) that
record only buys/sells/rights/bonus — no dividend lines — and they are distinct positions
from the iFast/Tiger/CDP holdings (e.g. AIMS: SRS 3,700u vs the iFast 34,090u lot), so
their distributions are nowhere in the parsed statements. We reconstruct them.

A dividend's per-unit rate is account-independent, so we source it locally first (the
goal: prefer info already in the files) and only reach online for genuine gaps:

  1. personal tracker  data/cdp-stocks/dividends.csv  — actual declared per-unit rates
     the user recorded by hand (2016 - mid-2022); cleanest where it exists.
  2. implied           build/dividends.csv gross / build/ledger.csv units of the paying
     account at that date — the user's own statement data (covers 2022-2026).
  3. SGX               api.sgx.com corporate-actions — official declared rate, also the
     date/currency spine (it lists every ex/pay date for each counter).
  4. Yahoo             query1.finance.yahoo.com — last resort (amounts are split/bonus/
     rights-adjusted, so only trusted when nothing local exists).

Units held at each ex-date are replayed from the CPF/SRS ledger; gross = units * rate.
SGX supplies the authoritative currency per distribution (e.g. IREIT switched SGD->EUR).
"""
import csv, os, re, time, json, urllib.request, urllib.parse, datetime as dt
from collections import defaultdict

from _csvout import write_csv
from _dates import try_date

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "cpf-srs-dividends.csv")

# ticker -> (exact SGX name, yahoo symbol, tracker stock name)
SEC = {
    "F34":  ("WILMAR INTERNATIONAL LIMITED",   "F34",  "Wilmar"),
    "Z74":  ("SINGTEL",                        "Z74",  "SingTel"),
    "D05":  ("DBS GROUP HOLDINGS LTD",         "D05",  "DBS"),
    "C52":  ("COMFORTDELGRO CORPORATION LTD",  "C52",  "Comfort Delgro"),
    "UD1U": ("IREIT GLOBAL",                   "UD1U", "IREIT Global"),
    "O5RU": ("AIMS APAC REIT",                 "O5RU", "AIMS APAC Reit"),
    "S61":  ("SBS TRANSIT LTD",                "S61",  "SBS Transit"),
}
ACCOUNTS = {"CPF": "cpf-stocks/transactions.csv", "SRS": "srs-stocks/transactions.csv"}
DIV_TICKERS = set(SEC)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def epoch_date(ms):
    return dt.date.fromtimestamp(ms / 1000) if ms else None


def pdate(s):
    return try_date(s, ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%Y-%m"))


def nearest(d, pool, days):
    best, bestdiff = None, days + 1
    for x in pool:
        diff = abs((x - d).days)
        if diff < bestdiff:
            best, bestdiff = x, diff
    return best


# ---------- CPF / SRS holdings (qty timeline replayed from their own files) ----------
def load_txns():
    book = defaultdict(lambda: defaultdict(list))
    for acct, rel in ACCOUNTS.items():
        for r in csv.DictReader(open(os.path.join(DATA, rel), encoding="utf-8-sig")):
            code = (r["Code"] or "").strip()
            if code not in DIV_TICKERS:
                continue
            book[acct][code].append((pdate(r["Date"]), float(str(r["Qty"]).replace(",", ""))))
    return book


def qty_at(events, asof):
    return sum(q for d, q in events if d and d <= asof)


# ---------- local rate source #1: personal tracker (explicit per-unit rates) ----------
def load_tracker():
    p = os.path.join(DATA, "cdp-stocks", "dividends.csv")
    name2tkr = {v[2]: k for k, v in SEC.items()}
    out = defaultdict(list)
    if not os.path.exists(p):
        return out
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        t = name2tkr.get((r["Stock Name"] or "").strip())
        rate = re.sub(r"[^\d.]", "", r.get("Dividend") or "")
        d = pdate(r["Date"])
        if t and rate and d:
            out[t].append((d, float(rate)))
    return out


# ---------- local rate source #2: implied = existing dividend gross / ledger units ----------
def _skip_acct(a):
    return ("dup" in a) or ("superseded" in a) or ("legacy" in a) or a in ("CPF", "SRS")


def load_ledger_units():
    ev = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(HERE, "ledger.csv"))):
        t, a, q = r["ticker"], r["account"], r["qty_signed"]
        if t in DIV_TICKERS and not _skip_acct(a) and q not in ("", "None", None):
            d = pdate(r["date"])
            if d:
                ev[(a, t)].append((d, float(q)))
    return ev


def load_implied(units_ev):
    """{ticker: [(pay_date, rate, ccy)]} from build/dividends.csv gross / paying-account units."""
    agg, ccy = defaultdict(float), {}
    for r in csv.DictReader(open(os.path.join(HERE, "dividends.csv"))):
        t, a = r["ticker"], r["account"]
        if t not in DIV_TICKERS or _skip_acct(a):
            continue
        d = pdate(r["date"])
        if d:
            agg[(a, t, d)] += float(r["gross"])
            ccy[(a, t, d)] = r["currency"]
    out = defaultdict(list)
    for (a, t, d), g in agg.items():
        u = qty_at(units_ev.get((a, t), []), d)
        if u > 0:
            out[t].append((d, g / u, ccy[(a, t, d)]))
    return out


# ---------- online rate source #3/#4: SGX (spine) + Yahoo (last resort) ----------
RATE_RX = re.compile(r"\b(SGD|USD|EUR|HKD)\s*([0-9]+(?:\.[0-9]+)?)")


def sgx_schedule(name):
    """{exDate: {pay, ccy, inline, has_opt}} — see module docstring; supplies the date spine."""
    url = "https://api.sgx.com/corporateactions/v1.0?cat=DIVIDEND&name=" + urllib.parse.quote(name)
    data = _get(url).get("data") or []
    by_ex, seen = {}, set()
    for r in data:
        if r.get("name") != name or r.get("anncType") != "DIVIDEND":
            continue
        ex = epoch_date(r.get("exDate"))
        if not ex:
            continue
        slot = by_ex.setdefault(ex, {"pay": epoch_date(r.get("datePaid")) or epoch_date(r.get("recDate")) or ex,
                                     "ccy": None, "inline": 0.0, "has_opt": False})
        part = r.get("particulars") or ""
        if "Cash Option" in part or "Scrip" in part:
            slot["has_opt"] = True
        m = RATE_RX.search(part)
        if m:
            dkey = (ex, m.group(1), round(float(m.group(2)), 8))
            if dkey in seen:
                continue
            seen.add(dkey)
            slot["ccy"] = slot["ccy"] or m.group(1)
            slot["inline"] = round(slot["inline"] + float(m.group(2)), 8)
    return by_ex


def yahoo_divs(sym):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.SI"
           f"?period1=1262304000&period2=1893456000&interval=1d&events=div")
    try:
        ev = _get(url)["chart"]["result"][0].get("events", {}).get("dividends", {})
    except Exception:
        return {}
    return {epoch_date(v["date"] * 1000): float(v["amount"]) for v in ev.values()}


def main():
    book = load_txns()
    tracker = load_tracker()
    implied = load_implied(load_ledger_units())
    today = dt.date.today()
    rows = []
    for ticker, (name, ysym, _) in SEC.items():
        sched = sgx_schedule(name)
        time.sleep(0.3)
        ydiv = yahoo_divs(ysym)
        for ex, s in sched.items():
            # resolve total per-unit rate: tracker -> implied -> SGX inline -> Yahoo
            rate, src, ccy = None, None, s["ccy"]
            td = nearest(s["pay"], [d for d, _ in tracker.get(ticker, [])], days=12)
            if td is not None:
                rate, src = next(r for d, r in tracker[ticker] if d == td), "tracker"
            if rate is None:
                im = nearest(s["pay"], [d for d, _, _ in implied.get(ticker, [])], days=12)
                if im is not None:
                    _, rate, ic = next((d, r, c) for d, r, c in implied[ticker] if d == im)
                    src, ccy = "implied", (ccy or ic)
            if rate is None and not s["has_opt"] and s["inline"] > 0:
                rate, src = s["inline"], "sgx"
            if rate is None:
                yd = nearest(ex, ydiv, days=3)
                if yd is not None:
                    rate, src, ccy = ydiv[yd], "yahoo", (ccy or "SGD")
            s.update(rate=rate, src=src, ccy=ccy or "SGD")
        for acct, tmap in book.items():
            events = tmap.get(ticker)
            if not events:
                continue
            for ex, s in sorted(sched.items()):
                if not s["rate"] or s["rate"] <= 0 or s["pay"] > today:
                    continue
                q = qty_at(events, ex)
                if q <= 0:
                    continue
                rate = round(s["rate"], 6)
                rows.append(dict(
                    date=s["pay"].isoformat(), account=acct, market="SG", ticker=ticker, name=name.title(),
                    kind="cash", gross=round(q * rate, 2), units=q, rate=rate, currency=s["ccy"],
                    source=f"{s['src']} (cpf/srs retrieval)",
                ))
    rows.sort(key=lambda r: (r["account"], r["ticker"], r["date"]))
    cols = ["date", "account", "market", "ticker", "name", "kind", "gross", "units", "rate", "currency", "source"]
    write_csv(OUT, cols, rows)
    print(f"{len(rows)} CPF/SRS dividend rows -> {OUT}")
    tot, bysrc = defaultdict(lambda: defaultdict(float)), defaultdict(int)
    for r in rows:
        tot[r["account"]][r["currency"]] += r["gross"]
        bysrc[r["source"]] += 1
    for a in sorted(tot):
        print(" ", a, {c: round(v, 2) for c, v in tot[a].items()})
    print(" rate sources:", dict(bysrc))


if __name__ == "__main__":
    main()
