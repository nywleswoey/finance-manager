#!/usr/bin/env python3
"""Parse cash dividends / distributions from every statement source -> dividends.csv.

Sources:
  Tiger flex  : 'Dividends' section, rows with status 'Paid' (HK/SG/US; ccy by market)
  FSM/iFast   : 'Stock Dividend' rows that are 'Cash Dividend' / 'Cash in Lieu' (SGD)
  CDP         : 'Summary of Payments' in the monthly PDFs (SG)
  Moomoo      : dividend lines in the monthly PDFs (SG/US)
Endowus Amundi fund is accumulating -> no distributions.

Schema: date, account, market, ticker, name, kind, gross, currency, source
"""
import csv, glob, os, re
from collections import defaultdict

from _pdf import raw_text
from _csvout import write_csv
from _dates import try_date
from _ledgercommon import canon, norm_ticker, num

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")


def norm(sym, market):
    return canon(norm_ticker(sym, market))

def market_of(sym):
    if ".SI" in sym: return "SG"
    inner = sym.split("(")[-1].strip(") ")
    return "HK" if (inner.isdigit() or sym.strip().isdigit()) else "US"

CCY = {"HK": "HKD", "SG": "SGD", "US": "USD"}
DIV = []
def add(**k): DIV.append(k)

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
                add(date=row[4], account=acct, market=mkt, ticker=norm(sym, mkt),
                    name=re.sub(r"\s*\(.*\)$", "", sym), kind="cash",
                    gross=num(row[10]), currency=CCY[mkt], source="tiger (dividends)")

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

# ---------- CDP cash dividends (maintained spreadsheet export) ----------
# data/cdp-stocks/dividends.csv is the authoritative CDP dividend ledger (the prior
# PDF-statement parser missed whole years and every foreign-currency holding). Columns:
#   Date, Year, Month, Stock Name, Dividends (native), Dividends (SGD), Quantity, Dividend (rate)
# Dates are mixed "DD-Mon-YY" / Excel serials. Rows with a zero amount are declared-but-
# unfilled and skipped. Native amount + currency are stored; SGD conversion happens downstream.
import datetime as _dt
_XL_EPOCH = _dt.date(1899, 12, 30)
# CDP holding name -> canonical ticker (SGX codes; foreign trusts are SGX-listed in USD/EUR)
CDP_NAME2TK = {
    "AIMS APAC Reit": "O5RU", "Accordia Golf Tr": "ADQU", "Advancer Global": "43Q",
    "Asian Pay Tv Tr": "S7OU", "CapitaLandInvest": "9CI", "Centurion": "OU8",
    "Capitaland Integrated Commercial Trust": "C38U", "Comfort Delgro": "C52", "DBS": "D05",
    "Eagle Htrust USD": "LIW", "GuocoLand": "F17", "HRnetGroup": "CHZ", "Hock Lian Seng": "J2T",
    "Hongkong Land Holdings": "H78", "Hyphens Pharma": "1J5", "IREIT Global": "UD1U",
    "Jumbo": "42R", "Keppel Pacific Oak US Reit": "CMOU", "Manulife US Reit": "BTOU",
    "Mapletree PanAsia Com Tr": "N2IU", "Nordic": "MR7", "OCBC": "O39", "QAF": "Q01",
    "SBS Transit": "S61", "Sasseur Reit": "CRPU", "Sembcorp Industries": "U96",
    "Silverlake Axis": "5CP", "SingTel": "Z74", "Soibuild Biz Reit": "SV3U",
    "Starhill Global Reit": "P40U", "Stoneweg European Trust EUR": "SET", "Top Glove": "BVA",
    "UMS": "558", "Wilmar": "F34",
}
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

def cdp():
    """CDP cash dividends from the maintained tracker. The sheet is broader than CDP —
    it also lists holdings tracked by broker statements (Tiger/FSM/SRS), and keeps tracking
    a holding after it's transferred to another custodian. To avoid double-counting, a row
    is emitted only when NO broker-statement dividend exists for the same ticker within ±7
    days (those are already ingested). Runs LAST so DIV holds the other sources to dedup against."""
    p = os.path.join(DATA, "cdp-stocks", "dividends.csv")
    if not os.path.exists(p):
        return
    elsewhere = defaultdict(list)                         # ticker -> [date] from broker statements
    for x in DIV:
        iso = _cdp_date(x.get("date", ""))
        if iso:
            elsewhere[x["ticker"]].append(_dt.date.fromisoformat(iso))
    def tracked_elsewhere(tk, iso):
        dx = _dt.date.fromisoformat(iso)
        return any(abs((dx - e).days) <= 7 for e in elsewhere.get(tk, []))
    for r in csv.reader(open(p)):
        if len(r) < 8 or r[0].strip() in ("", "Date", "﻿Date"):
            continue
        d, _yr, _mo, name, nat, sgd, qty, rate = r[:8]
        name = name.strip()
        natg, sgdg = num(nat), num(sgd)
        if natg == 0 and sgdg == 0:                       # declared but no amount -> skip
            continue
        tk = CDP_NAME2TK.get(name)
        date = _cdp_date(d)
        if tk is None or date is None:
            continue
        if tracked_elsewhere(tk, date):                   # already in a broker statement -> skip
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
    # "<TKR> CASH DIVIDEND @ <CCY> <rate>" — currency + per-share rate stated explicitly
    rx = re.compile(r"([A-Z0-9]{2,6})\s+CASH DIVIDEND\s+@\s+([A-Z]{3})\s*([\d.]+)?")
    for f in sorted(glob.glob(os.path.join(DATA, "moomoo/moomoo_*.pdf"))):
        mo = re.search(r"(\d{6})", f).group(1); ym = f"{mo[:4]}-{mo[4:]}"
        txt = raw_text(f)
        lines = txt.splitlines()
        for i, ln in enumerate(lines):
            m = rx.search(ln)
            if not m: continue
            tkr = canon(m.group(1)); ccy = m.group(2)
            rate = num(m.group(3)) if m.group(3) else ""
            # amount: nearest "Corporate Action  +<amt>" in surrounding lines
            amt = 0.0
            for j in range(max(0, i - 3), min(len(lines), i + 3)):
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
        # US dividends use "<TKR> ... SHARES DIVIDENDS" + "US Dividend Paying +<gross>"
        rxus = re.compile(r"([A-Z]{1,5})\s+([\d.]+)\s+SHARES DIVIDENDS")
        for i, ln in enumerate(lines):
            mu = rxus.search(ln)
            if not mu: continue
            tkr = canon(mu.group(1)); units = num(mu.group(2)); amt = 0.0
            for j in range(max(0, i - 2), min(len(lines), i + 4)):
                a = re.search(r"US Dividend Paying\s+\+([\d,]+\.\d+)", lines[j])  # positive = gross
                if a: amt = num(a.group(1)); break
            if amt <= 0: continue
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

# ---------- run all sources ----------
tiger(); fsm(); moomoo(); cpf_srs(); cdp(); apply_corrections()   # cdp() last: dedups vs the rest
out = os.path.join(HERE, "dividends.csv")
cols = ["date", "account", "market", "ticker", "name", "kind", "gross", "units", "rate", "currency", "source"]
write_csv(out, cols, DIV, extrasaction="ignore")

# ---------- summary ----------
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
