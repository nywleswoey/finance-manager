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
import csv, glob, os, re, subprocess
from collections import defaultdict

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}
def canon(t): return ALIAS.get(t, t)

def norm(sym, market):
    sym = (sym or "").strip()
    m = re.search(r"\(([^)]+)\)\s*$", sym)
    if m: sym = m.group(1).strip()
    sym = re.sub(r"\.(SI|US|HK)$", "", sym, flags=re.I)
    if market == "HK" and re.fullmatch(r"\d+", sym): sym = sym.zfill(5)
    return canon(sym.upper())

def market_of(sym):
    if ".SI" in sym: return "SG"
    inner = sym.split("(")[-1].strip(") ")
    return "HK" if (inner.isdigit() or sym.strip().isdigit()) else "US"

def num(s):
    try: return float(str(s).replace(",", "").replace("$", ""))
    except ValueError: return 0.0

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
        add(date=r["Transaction Date"], account=acct, market="SG", ticker=code,
            name=name, kind="cash", gross=amt,
            currency=(r.get("Product Currency") or "SGD").strip(), source="fsm (stock dividend)")

# ---------- CDP statements (PDF) ----------
import importlib.util
_spec = importlib.util.spec_from_file_location("parse_cdp", os.path.join(HERE, "parse_cdp.py"))
_pcdp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_pcdp)
def cdp_code(name):
    name = name.strip()
    return _pcdp.NAME2CODE.get(name) or canon(re.sub(r"[^A-Z0-9]", "", name.upper())[:8])

def cdp():
    seen = set()
    # 2019+ format: "<date> <NAME> <Type> Cash Dividend - <qty> units @ SGD <rate>   <amount>"
    rx_new = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(.+?Cash Dividend.+?)\s+([\d,]+\.\d+)\s*$")
    # 2017-18 format: a 3-line block under "Summary of Payments"
    #   L1  <NAME>  <Reg'd Holdings>  SGD<Gross>  <Exchange Rate|->  SGD<Amount Paid>
    #   L2  DIVIDEND  <Book Close dd/mm/yyyy>  SGD<Tax>  SGD<Payment Rate>  <Handling Fee|->
    #   L3  <Type>    <Credit dd/mm/yyyy>      SGD<Net Amount>            <GST|->
    # The credit date is the cash pay date; units + per-share rate are stated explicitly.
    rx_sec = re.compile(
        r"^\s*([A-Z][A-Za-z0-9 &.\-/']+?)\s+([\d,]+)\s+SGD([\d,]+\.\d{2})\s+(?:-|[\d.]+)\s+SGD([\d,]+\.\d{2})\s*$")
    rx_pay = re.compile(r"(?:DIVIDEND|DISTRIB\w*)\s+(\d{2}/\d{2}/\d{4})\s+SGD[\d,]*\.?\d*\s+SGD([\d.]+)")
    rx_credit = re.compile(r"(\d{2}/\d{2}/\d{4})\s+SGD[\d,]+\.\d{2}")
    for f in sorted(glob.glob(os.path.join(DATA, "cdp-statements/*.pdf"))):
        txt = subprocess.run(["pdftotext", "-layout", f, "-"], capture_output=True, text=True).stdout
        lines = txt.splitlines()
        for i, ln in enumerate(lines):
            if "Payment Made" in ln: continue
            m = rx_new.match(ln.strip())
            if m:
                desc = m.group(2)
                name = re.split(r"\s+(?:Final|Interim|Special|Annual|1st|2nd|Cash Dividend)", desc)[0].strip()
                key = (m.group(1), name, m.group(3))
                if key in seen: continue
                seen.add(key)
                # "<qty> units @ SGD <rate>" — declared units + per-share rate stated in the PDF
                ur = re.search(r"([\d,]+(?:\.\d+)?)\s*units?\s*@\s*(?:SGD|S\$)?\s*([\d.]+)", desc)
                add(date=m.group(1), account="CDP", market="SG", ticker=cdp_code(name),
                    name=name.title(), kind="cash", gross=num(m.group(3)),
                    units=(num(ur.group(1)) if ur else ""), rate=(num(ur.group(2)) if ur else ""),
                    currency="SGD", source="cdp (cash dividend)")
                continue
            m = rx_sec.match(ln)
            if not m or m.group(1).strip() in ("Security", "Payment Type", "Dividend Type"):
                continue
            # L2 must be a DIVIDEND payment line; otherwise this is some other payment type.
            p = rx_pay.search(lines[i + 1]) if i + 1 < len(lines) else None
            if not p: continue
            c = rx_credit.search(lines[i + 2]) if i + 2 < len(lines) else None
            name = m.group(1).strip()
            pay_date = c.group(1) if c else p.group(1)   # credit date (fallback: book close)
            key = (pay_date, name, m.group(3))
            if key in seen: continue
            seen.add(key)
            add(date=pay_date, account="CDP", market="SG", ticker=cdp_code(name),
                name=name.title(), kind="cash", gross=num(m.group(3)),
                units=num(m.group(2)), rate=num(p.group(2)),
                currency="SGD", source="cdp (cash dividend)")

# ---------- Moomoo (PDF) ----------
def moomoo():
    seen = set()
    # "<TKR> CASH DIVIDEND @ <CCY> <rate>" — currency + per-share rate stated explicitly
    rx = re.compile(r"([A-Z0-9]{2,6})\s+CASH DIVIDEND\s+@\s+([A-Z]{3})\s*([\d.]+)?")
    for f in sorted(glob.glob(os.path.join(DATA, "moomoo/moomoo_*.pdf"))):
        mo = re.search(r"(\d{6})", f).group(1); ym = f"{mo[:4]}-{mo[4:]}"
        txt = subprocess.run(["pdftotext", "-layout", f, "-"], capture_output=True, text=True).stdout
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
tiger(); fsm(); cdp(); moomoo(); cpf_srs(); apply_corrections()
out = os.path.join(HERE, "dividends.csv")
cols = ["date", "account", "market", "ticker", "name", "kind", "gross", "units", "rate", "currency", "source"]
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
    for d in DIV: w.writerow(d)

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
