#!/usr/bin/env python3
"""Parse cash dividends / distributions from every statement source -> dividends.csv.

Sources:
  Tiger flex  : 'Dividends' section, rows with status 'Paid' (currency from the
                flex column; market inference only when that cell is blank)
  FSM/iFast   : 'Stock Dividend' rows that are 'Cash Dividend' / 'Cash in Lieu' (SGD)
  CDP         : the Cash Transaction section of each CDP statement PDF (see
                cdp_statements()); the data/cdp-stocks/dividends.csv tracker fills in
                for any payout whose month has no statement, and the tracker's own
                amount-backfill (see cdp())
  Moomoo      : dividend lines in the monthly PDFs (SG/US)
Endowus Amundi fund is accumulating -> no distributions.

Schema: date, account, market, ticker, name, kind, gross, currency, source
"""
import csv, glob, os, re
from collections import defaultdict

from _pdf import raw_text
from _csvout import write_csv
from _dates import try_date
from _ledgercommon import (MARKET_CCY, canon, cdp_dividend_ticker, market_of, name_to_ticker,
                           norm_ticker, num)

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")


def norm(sym, market):
    return canon(norm_ticker(sym, market))

DIV = []
def add(**k): DIV.append(k)

def tiger_currency(sym, explicit):
    """Payout currency for one Tiger flex dividend row.

    The flex file's last column is the cash currency when it holds a 3-letter code
    (HKD on Link, USD on a US name, SGD on an SGX name). A blank cell falls back to
    the market. A ticker-wide EUR override is the wrong refinement: SET and CWBU
    also pay SGD distributions, and those Tiger amounts equal quantity times the SGD
    gross rate with this column set to SGD. Forcing EUR would convert cash that is
    already SGD."""
    code = (explicit or "").strip().upper()
    if len(code) == 3 and code.isalpha():
        return code
    return MARKET_CCY[market_of(sym)]

# ---------- Tiger ----------
def tiger():
    for pat, acct in [("tiger-prime/*.csv", "Tiger Prime"),
                      ("tiger-cash-boost/*.csv", "Tiger Cash Boost")]:
        for f in glob.glob(os.path.join(DATA, pat)):
            for row in csv.reader(open(f, encoding="utf-8-sig")):
                if not (row and row[0] == "Dividends" and len(row) > 10 and row[3] == "DATA"):
                    continue
                if row[9].strip() != "Paid":            # only cash received; ignore accruals
                    continue
                sym = row[6].strip(); mkt = market_of(sym)
                explicit = row[14] if len(row) > 14 else ""
                add(date=row[4], account=acct, market=mkt, ticker=norm(sym, mkt),
                    name=re.sub(r"\s*\(.*\)$", "", sym), kind="cash",
                    gross=num(row[10]), currency=tiger_currency(sym, explicit),
                    source="tiger (dividends)")

# ---------- FSM / iFast ----------
def fsm():
    path = os.path.join(DATA, "fsm/ifast_historical.csv")
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["Transaction Type"] != "Stock Dividend": continue
        pn = r["Product Name"]
        if not ("Cash Dividend" in pn or "Cash in Lieu" in pn): continue   # skip scrip (=shares)
        amt = num(r.get("Product Amount"))
        if amt <= 0: continue
        m = re.search(r"\(([^)]+)\)\s*$", pn)
        code = canon(m.group(1).upper()) if m else ""
        method = (r.get("Payment Method") or "").strip()
        acct = {"SRS": "SRS", "CPFIS-OA": "CPF"}.get(method, "FSM")
        name = re.sub(r"\s*(Cash Dividend|Cash in Lieu).*$", "", pn).strip()
        ccy = (r.get("Product Currency") or "SGD").strip()
        mkt = "MY" if ccy.upper() == "MYR" else "SG"      # Bursa dividends land in MYR
        add(date=r["Transaction Date"], account=acct, market=mkt, ticker=code,
            name=name, kind="cash", gross=amt,
            currency=ccy, source="fsm (stock dividend)")

# ---------- CDP cash dividends (statement PDFs, authoritative) ----------
# Each CDP statement PDF's "Cash Transaction" section lists every cash dividend CDP paid
# that month: "<DD/MM/YYYY>  <ISSUER NAME> [Final/Interim/Special] Cash Dividend - <units>
# units @ <CCY> <rate>   <amount>" (REIT distributions sometimes read "<issuer> [Interim]
# Dividend Option - ..." instead of "Cash Dividend"). "Capital Distribution"/"Redemption"
# rows share the same column shape but are not dividend income, so the kind suffix is part
# of the match, not stripped first. "Payment Made" settlement legs have no "units @" clause
# and never match.
_CASH_DIV_LINE = re.compile(
    r"^\s*(\d{2})/(\d{2})/(\d{4})\s+(.+?(?:Cash Dividend|Dividend Option))\s+-\s+"
    r"([\d,]+)\s+units\s+@\s+([A-Z]{3})\s*([\d.]+)\s+([\d,]+\.\d{2})\s*$")
_CASH_DIV_KIND = re.compile(r"\s+(?:Final|Interim|Special)?\s*(?:Cash Dividend|Dividend Option)\s*$",
                            re.I)

def cdp_statement_issuer(name_and_kind):
    """Strip the trailing Final/Interim/Special Cash Dividend / Dividend Option words off
    a Cash Transaction description, leaving the issuer name symbols.csv's `names` column
    maps (the same display names parse_cdp.py resolves for the holdings table)."""
    return _CASH_DIV_KIND.sub("", name_and_kind).strip()

def cdp_statements():
    """CDP cash dividends read straight from every data/cdp-statements/*.pdf's Cash
    Transaction section. This is the authoritative record — CDP pays cash straight into
    the account, so every payout appears there. Runs BEFORE cdp() (the tracker-sheet
    fallback below) so that function's existing ±7-day ticker dedup (see tracked_elsewhere)
    skips any tracker row already booked here, instead of a separate month-level rule."""
    unmapped = set()
    for f in sorted(glob.glob(os.path.join(DATA, "cdp-statements", "*.pdf"))):
        txt = raw_text(f) or ""
        lines = txt.splitlines()
        start = end = None
        for i, ln in enumerate(lines):
            if start is None and "Cash Transaction" in ln:
                start = i
            elif start is not None and re.search(r"Your Securities Account|- END -", ln):
                end = i
                break
        if start is None:
            continue
        for ln in lines[start:end]:
            m = _CASH_DIV_LINE.match(ln)
            if not m:
                continue
            dd, mm, yyyy, name_kind, units, ccy, rate, amt = m.groups()
            name = cdp_statement_issuer(name_kind)
            tk = name_to_ticker(name)
            if tk is None:
                unmapped.add(name)
                continue
            add(date=f"{yyyy}-{mm}-{dd}", account="CDP", market="SG", ticker=tk,
                name=name, kind="cash", gross=num(amt), units=num(units), rate=num(rate),
                currency=ccy, source="cdp (cash dividend, statement)")
    if unmapped:
        print("CDP statement dividends: UNMAPPED issuer names (review):", sorted(unmapped))

# ---------- CDP cash dividends (maintained spreadsheet, fallback) ----------
# data/cdp-stocks/dividends.csv only fills in months with no statement PDF on disk (old
# statements, or a gap in what's been downloaded) — cdp_statements() above now reads every
# covered month straight from the authoritative Cash Transaction section. Columns:
#   Date, Year, Month, Stock Name, Dividends (native), Dividends (SGD), Quantity, Dividend (rate)
# Dates are mixed "DD-Mon-YY" / Excel serials. A zero-amount row is backfilled as rate x the
# CDP custody position (see LEDGER_CSV) when one is held, else skipped as declared-but-unfilled.
# Native amount + currency are stored; SGD conversion happens downstream.
import datetime as _dt
_XL_EPOCH = _dt.date(1899, 12, 30)
# foreign-currency CDP holdings (others are SGD); used when native != SGD column
CDP_FCCY = {"LIW": "USD", "SET": "EUR", "BTOU": "USD", "CMOU": "USD", "H78": "USD", "UD1U": "EUR"}
# manual corrections to the CDP sheet, keyed by (ticker, ISO pay-date). The sheet is a broader
# tracker and occasionally mis-records. Value None = drop the row; a dict = override gross/sgd/units.
CDP_DIV_FIX = {
    # 2021 Accordia "dividend" is the remainder of the delisting payout — booked as txn proceeds,
    # not income (position already sold 2020-10-15).
    ("ADQU", "2021-08-17"): None,
    # CDP held only 1,400 Stoneweg on this date; the sheet's 14,500 units (and 1,260.78) also
    # counted the 13,100 later held in Tiger Prime. Scale to the CDP-only 1,400.
    ("SET", "2022-09-28"): {"gross": 121.73, "sgd": 171.21, "units": 1400},
}

def _cdp_date(d):
    d = (d or "").strip()
    if re.fullmatch(r"\d{4,6}", d):                       # Excel serial
        return (_XL_EPOCH + _dt.timedelta(days=int(d))).isoformat()
    dd = try_date(d, ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y"))
    return dd.isoformat() if dd else None

# build/ledger.csv (parse_cdp.py's statement snapshot-diff, via build_ledger.py — see the
# `flat` Makefile target order) holds the CDP custody position. The tracker sheet stopped
# having a human fill in its amount/quantity columns at some point (left '#N/A' or '0' while
# still recording the per-unit rate); a row like that is backfilled from the statement
# position instead of being dropped, so overridable in tests as pd.LEDGER_CSV.
LEDGER_CSV = os.path.join(HERE, "ledger.csv")

def _cdp_statement_months():
    """YYYY-MM of every CDP statement PDF on disk (the months parse_cdp.py snapshots)."""
    months = set()
    for f in glob.glob(os.path.join(DATA, "cdp-statements", "*.pdf")):
        m = re.search(r"(\d{4})(\d{2})", os.path.basename(f))
        if m:
            months.add(f"{m.group(1)}-{m.group(2)}")
    return months

def _cdp_snapshot_month(iso_date):
    """The statement month whose -28 ledger leg is the latest on or before `iso_date`.
    Across a statement gap that leg lumps every change in the gap, so the position on a
    date whose snapshot month has no statement is stale and must not be backfilled."""
    dd = _dt.date.fromisoformat(iso_date)
    if dd.day < 28:
        dd = dd.replace(day=1) - _dt.timedelta(days=1)
    return f"{dd.year:04d}-{dd.month:02d}"

def _cdp_position_on(positions, ticker, iso_date):
    """Shares of `ticker` the CDP account held on `iso_date` (ISO), from a cumulative
    sum of every dated qty_signed up to and including that date."""
    return sum(q for d, q in positions.get(ticker, ()) if d <= iso_date)

def _load_cdp_positions():
    pos = defaultdict(list)
    if not os.path.exists(LEDGER_CSV):
        return pos
    for r in csv.DictReader(open(LEDGER_CSV)):
        if r["account"] != "CDP":
            continue
        pos[r["ticker"]].append((r["date"], num(r["qty_signed"])))
    return pos

def cdp():
    """CDP cash dividends from the maintained tracker — now only a fallback for a payout
    cdp_statements() didn't already read straight off a statement PDF (an older statement
    with no Cash Transaction section, a month with no PDF on disk at all, or a Cash
    Transaction line a future statement layout change breaks). Any row within ±7 days of a
    cdp_statements() row for the same ticker is skipped outright, backfilled or not: a
    blended per-unit sheet rate can cover two same-day REIT tranches, or bake in a
    capital-return component the statement text itself does not, so the direct reading
    wins whenever one exists. The sheet is also broader than CDP — it lists holdings
    tracked by broker statements (Tiger/FSM/SRS) too, and keeps tracking a holding after
    it's transferred to another custodian — so beyond that, a sheet-stated amount is
    emitted only when no broker-statement dividend exists for the same ticker within ±7
    days (those are already ingested); a backfilled row is exempt from only that broker
    check, since its gross is rate x the CDP-only position and so can't overlap a payout
    booked at a different custodian. Backfill only uses a position backed by a statement
    (see _cdp_snapshot_month). Runs LAST so DIV holds the other sources to dedup against."""
    p = os.path.join(DATA, "cdp-stocks", "dividends.csv")
    if not os.path.exists(p):
        return
    elsewhere = defaultdict(list)            # ticker -> [date] from a broker's own statement
    from_statement = defaultdict(list)       # ticker -> [date] cdp_statements() already read
    for x in DIV:
        iso = _cdp_date(x.get("date", ""))
        if not iso:
            continue
        bucket = from_statement if x["source"] == "cdp (cash dividend, statement)" else elsewhere
        bucket[x["ticker"]].append(_dt.date.fromisoformat(iso))
    def _within_7_days(tk, iso, bucket):
        dx = _dt.date.fromisoformat(iso)
        return any(abs((dx - e).days) <= 7 for e in bucket.get(tk, []))
    def tracked_elsewhere(tk, iso):
        return _within_7_days(tk, iso, elsewhere)
    positions = _load_cdp_positions()
    statements = _cdp_statement_months()
    for r in csv.reader(open(p)):
        if len(r) < 8 or r[0].strip() in ("", "Date", "﻿Date"):
            continue
        d, _yr, _mo, name, nat, sgd, qty, rate = r[:8]
        name = name.strip()
        natg, sgdg = num(nat), num(sgd)
        tk = cdp_dividend_ticker(name)
        date = _cdp_date(d)
        if tk and date and _within_7_days(tk, date, from_statement):
            # cdp_statements() already read this exact payout straight off the statement's
            # own Cash Transaction section. Checked (and skipped) even for a row the sheet
            # would otherwise backfill: real data shows the sheet's one blended rate can
            # cover two same-day REIT distribution tranches, or bake in a capital-return
            # component the Cash Transaction line does not — the statement reading wins.
            continue
        backfilled = False
        if natg == 0 and tk and date and _cdp_snapshot_month(date) in statements:
            # the sheet knows the per-unit rate but never filled the amount -> recover it
            # from the statement-derived custody position instead of dropping the payout.
            held = _cdp_position_on(positions, tk, date)
            rate_num = num(rate)
            if held > 0 and rate_num:
                natg, qty, backfilled = round(rate_num * held, 2), held, True
        if natg == 0 and sgdg == 0:                       # still nothing -> declared but unfilled
            continue
        if tk is None or date is None:
            continue
        if not backfilled and tracked_elsewhere(tk, date):  # already in a broker statement
            continue
        fix = CDP_DIV_FIX.get((tk, date))                 # manual corrections (see dict above)
        if fix is None and (tk, date) in CDP_DIV_FIX:     # explicit drop
            continue
        if fix:
            natg, sgdg, qty = fix["gross"], fix["sgd"], fix["units"]
        ccy = "SGD" if abs(natg - sgdg) < 0.01 else CDP_FCCY.get(tk, "SGD")
        add(date=date, account="CDP", market="SG", ticker=tk, name=name, kind="cash",
            gross=num(natg), units=num(qty), rate=num(rate), currency=ccy,
            source="cdp (cash dividend)")

# ---------- Moomoo (PDF) ----------
def moomoo():
    seen = set()
    # "<TKR> CASH DIVIDEND @|AT <CCY> <rate>" — currency + per-share rate stated explicitly.
    # Moomoo's own export has flip-flopped between "@" and "AT" (and upper/lower case) across
    # statement months, so both are accepted; only the connector + "CASH DIVIDEND" wording is
    # case-insensitive — the ticker and currency stay upper-case-only matches.
    rx = re.compile(r"([A-Z0-9]{2,6})\s+(?i:CASH DIVIDEND\s+(?:@|AT))\s+([A-Z]{3})\s*([\d.]+)?")
    for f in sorted(glob.glob(os.path.join(DATA, "moomoo/moomoo_*.pdf"))):
        mo = re.search(r"(\d{6})", f).group(1); ym = f"{mo[:4]}-{mo[4:]}"
        txt = raw_text(f)
        lines = txt.splitlines()
        for i, ln in enumerate(lines):
            m = rx.search(ln)
            if not m: continue
            tkr = canon(m.group(1)); ccy = m.group(2)
            rate = num(m.group(3)) if m.group(3) else ""
            # amount: nearest "Corporate Action  +<amt>" at or after this line (same line
            # when the two share it; a line or two later when a long rate — e.g. several
            # tranches on one statement — pushes the rate text past the amount column).
            # Forward-only: scanning backward too would, for two same-ticker tranches a
            # few lines apart, grab the EARLIER tranche's amount for the second match.
            amt = 0.0
            for j in range(i, min(len(lines), i + 3)):
                a = re.search(r"Corporate Action\s+\+([\d,]+\.\d+)", lines[j])
                if a: amt = num(a.group(1)); break
            if amt <= 0: continue
            key = (ym, tkr, amt)
            if key in seen: continue
            seen.add(key)
            mkt = "SG" if ccy == "SGD" else ("HK" if ccy == "HKD" else "US")
            add(date=ym + "-15", account="Moomoo", market=mkt, ticker=tkr,
                name=tkr, kind="cash", gross=amt, currency=ccy, rate=rate,
                source="moomoo (cash dividend)")
        # US dividends: a "<TKR> <units> SHARES[ DIVIDENDS]" anchor is immediately followed by
        # its own "US Dividend Paying"/"Corporate Action" entry carrying the signed amount — a
        # receipt (+) is the dividend, the same-shaped "WITHHOLDING TAX" leg right after it (-)
        # is skipped. Which label is used, and whether "DIVIDENDS" sits on the anchor line or
        # wraps onto the amount line instead, has both varied across statement months; requiring
        # the word "DIVIDEND" somewhere in the pair (rather than on a fixed line) keeps both eras
        # working and keeps an unrelated SHARES-shaped corporate action (e.g. a split) unbooked.
        rxus = re.compile(r"([A-Z]{1,5})\s+([\d.]+)\s+SHARES\b")
        amtus = re.compile(r"(?:US Dividend Paying|Corporate Action)\s+([+-][\d,]+\.\d+)")
        for i, ln in enumerate(lines):
            mu = rxus.search(ln)
            if not mu: continue
            tkr = canon(mu.group(1)); units = num(mu.group(2)); amt = 0.0; pair = ln
            for j in range(i, min(len(lines), i + 4)):
                a = amtus.search(lines[j])
                if a: amt = num(a.group(1)); pair += lines[j]; break
            if amt <= 0 or "DIVIDEND" not in pair.upper(): continue
            key = (ym, tkr, amt, "us")
            if key in seen: continue
            seen.add(key)
            add(date=ym + "-15", account="Moomoo", market="US", ticker=tkr,
                name=tkr, kind="cash", gross=amt, currency="USD", units=units,
                rate=(round(amt / units, 6) if units else ""),
                source="moomoo (cash dividend)")

# ---------- CPF / SRS (backfilled into data/cpf-srs-dividends.csv by fetch_cpf_srs_dividends.py) ----------
def cpf_srs():
    p = os.path.join(DATA, "cpf-srs-dividends.csv")
    if not os.path.exists(p):
        return
    for r in csv.DictReader(open(p)):
        add(date=r["date"], account=r["account"], market=r["market"], ticker=r["ticker"],
            name=r["name"], kind=r["kind"], gross=num(r["gross"]),
            units=num(r["units"]), rate=num(r["rate"]), currency=r["currency"],
            source=r["source"])

# ---------- one-time external retrievals ----------
# For dividends whose statement omits units/rate AND whose ledger holds no position at the
# pay date, the per-share rate is fetched once from Yahoo Finance (finance-manager-v2's
# approach: GET query1.finance.yahoo.com/v8/finance/chart/<ticker>.SI?events=div). units is
# then gross / rate; each is cross-checked so gross == round(units * rate, 2).
#   (account, ticker, date, gross): (units, rate)
CORRECTIONS = {
    # Sembcorp Ind U96 — no ledger position at pay date; Yahoo ex 2022-04-26 @ SGD0.03.
    ("FSM", "U96", "10 May 2022", 90.0): (3000.0, 0.03),
}
def apply_corrections():
    for d in DIV:
        k = (d.get("account"), d.get("ticker"), d.get("date"), d.get("gross"))
        if k in CORRECTIONS and not d.get("units") and not d.get("rate"):
            d["units"], d["rate"] = CORRECTIONS[k]

def main():
    DIV.clear()
    # cdp() last: dedups vs the rest (including cdp_statements(), so a tracker-sheet row
    # for a month already read straight off a statement is skipped, not double-counted)
    tiger(); fsm(); moomoo(); cpf_srs(); cdp_statements(); cdp(); apply_corrections()
    out = os.path.join(HERE, "dividends.csv")
    cols = ["date", "account", "market", "ticker", "name", "kind", "gross", "units", "rate", "currency", "source"]
    write_csv(out, cols, DIV, extrasaction="ignore")

    by_ccy = defaultdict(lambda: defaultdict(float))
    for d in DIV: by_ccy[d["currency"]][d["market"]] += d["gross"]
    print(f"dividend rows: {len(DIV)} -> {out}")
    print("\n=== total dividends by currency × market ===")
    for ccy in sorted(by_ccy):
        for mkt, v in sorted(by_ccy[ccy].items()):
            print(f"  {ccy} {mkt}: {v:>12,.2f}")
    bysrc = defaultdict(int)
    for d in DIV: bysrc[d["source"]] += 1
    print("\nby source:", dict(bysrc))
    return DIV


if __name__ == "__main__":
    main()
