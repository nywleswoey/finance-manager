#!/usr/bin/env python3
"""Unified transaction ledger builder.

Parses every machine-readable source under data/ into one normalized schema,
writes build/ledger.csv (the timeline), then replays share-affecting events
per (account, ticker) and compares to Holdings.md to surface discrepancies.

Normalized row schema:
  date, account, market, ticker, asset_type, action, qty_signed,
  price, amount, currency, fees, source, raw
"""
import csv, glob, os, re, sys
from collections import defaultdict
from datetime import datetime

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
ROOT = os.path.join(os.path.dirname(__file__), "..")

# ---------- helpers ----------
def num(s):
    if s is None: return 0.0
    s = str(s).strip().replace(",", "").replace("$", "")
    if s in ("", "-", "--"): return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try: v = float(s)
    except ValueError: return 0.0
    return -v if neg else v

# Holdings.md label  ->  canonical SGX/exchange code used in transaction data
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}  # CWBU->SET: SGX counter renamed (Cromwell->Stoneweg)
def canon(t):
    return ALIAS.get(t, t)

def norm_ticker(sym, market):
    if not sym: return ""
    sym = sym.strip()
    m = re.search(r"\(([^)]+)\)\s*$", sym)          # "Link Reit (00823)" -> 00823
    if m: sym = m.group(1).strip()
    sym = re.sub(r"\.(SI|US|HK)$", "", sym, flags=re.I)
    if market == "HK" and re.fullmatch(r"\d+", sym):
        sym = sym.zfill(5)
    return sym.upper()

def parse_date(s):
    s = (s or "").strip().split("\n")[0].split(",")[0].strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%Y%m%d"):
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: pass
    return s  # leave raw if unknown

LEDGER = []
MARKET_CCY = {"SG": "SGD", "US": "USD", "HK": "HKD"}
def add(**k):
    k.setdefault("price", ""); k.setdefault("amount", ""); k.setdefault("fees", "")
    k.setdefault("currency", ""); k.setdefault("market", ""); k.setdefault("ticker", "")
    k.setdefault("asset_type", "stock"); k.setdefault("raw", "")
    # standardise currency: SG/CDP/CPF/SRS sources omit it -> derive from market.
    # FX cash transfers set currency explicitly, so the empty-check leaves them intact.
    if not str(k["currency"]).strip():
        k["currency"] = MARKET_CCY.get(k["market"], "")
    LEDGER.append(k)

# ---------- simple CSV sources (cdp / cpf / srs / vickers / archive tiger) ----------
SIMPLE = {
    "cdp-stocks/transactions.csv": "CDP-csv(superseded)",   # gappy; CDP statements are authoritative
    "cpf-stocks/transactions.csv": "CPF",
    "srs-stocks/transactions.csv": "SRS",
    "vickers-stocks/transactions.csv": "Vickers(legacy)",
    ".archive/tiger-stocks/transactions.csv": "Tiger-archive(dup-superseded)",  # duplicates tiger-prime flex
}
# action -> sign on quantity (None = non-position cash event)
SIMPLE_SIGN = {
    "open market": None,        # sign comes from amount; qty sign decided below
    "ipo": +1, "private placement": +1, "rights issue": +1,
    "bonus issuance": +1, "script dividend": +1, "scrip dividend": +1,
    "transfer out": -1, "transfer in": +1,
}
def load_simple():
    for rel, acct in SIMPLE.items():
        path = os.path.join(DATA, rel)
        if not os.path.exists(path): continue
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            mkt = (r.get("Market") or "").strip()
            code = norm_ticker(r.get("Code") or "", mkt)
            if not code: continue
            if code == "0P0001OOJG": continue   # Amundi Prime USA fund -> Endowus is authoritative (has fees)
            code = canon(code)
            qty = num(r.get("Qty"))          # raw Qty is already signed (sells/transfers negative)
            act = (r.get("Action") or "").strip().lower()
            amt = num(r.get("Amount"))
            add(date=parse_date(r.get("Date")), account=acct, market=mkt, ticker=code,
                action=act or "open market", qty_signed=qty,
                price=r.get("Unit Price", "").strip(), amount=amt,
                currency=(r.get("Currency") or "").strip(), source=rel, raw=r.get("Stock Name", ""))

# ---------- Tiger flex statements (prime + cash boost) ----------
TIGER = [("tiger-prime/*.csv", "Tiger Prime"),
         ("tiger-cash-boost/*.csv", "Tiger Cash Boost")]
def load_tiger():
    for pat, acct in TIGER:
        for f in sorted(glob.glob(os.path.join(DATA, pat))):
            rel = os.path.relpath(f, DATA)
            hdr = None
            for row in csv.reader(open(f, encoding="utf-8-sig")):
                if not row: continue
                sec = row[0]
                if sec == "Trades":
                    if len(row) > 4 and row[3] == "HEADER": hdr = row; continue
                    if len(row) > 8 and row[3] == "DATA":
                        atype = row[1]              # Stock / Option / Fund / Forex
                        sym = row[4]
                        if not sym: continue        # continuation row
                        mkt = row[5]
                        qty = num(row[8])
                        if atype in ("Forex",):     # currency conversion, not a position
                            add(date=parse_date(row[-3] if len(row) > 3 else ""), account=acct,
                                market=mkt, ticker="", asset_type="forex", action="forex",
                                qty_signed=0, amount=num(row[10]), currency=row[-1],
                                source=rel, raw=sym); continue
                        tt = row[-3] if len(row) >= 3 else ""   # Trade Time near end
                        note = row[-4].strip().lower() if len(row) >= 4 else ""
                        # Trades flagged "Settled via SRS/CPF account" belong to the SRS/CPF
                        # account (and are also in the authoritative srs-/cpf-stocks files) ->
                        # tag as dup so they neither pollute the Tiger cash account nor double-count.
                        racct = acct
                        if "srs account" in note: racct = "SRS(via-Tiger-dup)"
                        elif "cpf account" in note: racct = "CPF(via-Tiger-dup)"
                        # Tiger "Fund" trades are USD money-market cash sweeps -> treat as
                        # cash (not a tracked position); only real stocks/options reconcile.
                        atype_l = "cash" if atype == "Fund" else atype.lower()
                        add(date=parse_date(tt), account=racct, market=mkt,
                            ticker=canon(norm_ticker(sym, mkt)), asset_type=atype_l,
                            action=("buy" if qty > 0 else "sell"), qty_signed=qty,
                            price=row[9], amount=num(row[10]), fees="",
                            currency=row[-1], source=rel, raw=sym)
                elif sec == "Transfer" and len(row) > 14 and row[3] == "DATA" and row[4] == "Stock":
                    # gifted / transferred-in shares (e.g. BABA, AMZN gifts)
                    method = row[7].strip()
                    sym = row[5]; mkt = "US" if re.fullmatch(r"[A-Z.]+", sym) else ("HK" if sym.isdigit() else "SG")
                    q = num(row[10]) * (-1 if "OUT" in method.upper() else 1)
                    add(date=parse_date(row[6]), account=acct, market=mkt,
                        ticker=canon(norm_ticker(sym, mkt)), asset_type="stock",
                        action=method.lower(), qty_signed=q,
                        price=row[12], amount=num(row[13]), currency=row[14],
                        source=rel, raw=method)
                elif sec == "Deposits & Withdrawals" and len(row) > 7 and row[3] == "DATA":
                    add(date=parse_date(row[4]), account=acct, asset_type="cash",
                        action=row[5].lower(), qty_signed=0, amount=num(row[6]),
                        currency=row[7], ticker="", source=rel, raw="D&W")
                elif sec == "Segment Transfer" and len(row) > 7 and row[3] == "DATA":
                    add(date=parse_date(row[4].split("~")[-1]), account=acct, asset_type="cash",
                        action="segment_transfer", qty_signed=0, amount=num(row[5]),
                        currency=row[7], ticker="", source=rel, raw="seg")

# ---------- FSM / iFast ----------
FSM_POS = {"Buy": +1, "Sell": -1, "Transfer In": +1, "Transfer Out": -1}
def load_fsm():
    path = os.path.join(DATA, "fsm/ifast_historical.csv")
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        t = (r.get("Transaction Type") or "").strip()
        pn = (r.get("Product Name") or "").strip()
        # iFast export co-mingles accounts; route by Payment Method.
        # SRS/CPFIS rows duplicate the authoritative srs-/cpf-stocks files -> tag, don't count under FSM.
        method = (r.get("Payment Method") or "").strip()
        fsm_acct = {"SRS": "SRS(via-iFast-dup)", "CPFIS-OA": "CPF(via-iFast-dup)"}.get(method, "FSM")
        qty = num(r.get("Quantity"))
        # only product names carrying a (CODE) are equity-like
        m = re.search(r"\(([^)]+)\)\s*$", pn)
        is_stock = bool(m) and "Cash Account" not in pn and "Auto-Sweep" not in pn
        code = canon(norm_ticker(pn, "SG")) if is_stock else ""
        action = t.lower()
        sign = FSM_POS.get(t)
        scrip = "Scrip" in pn
        if t == "Stock Dividend" and scrip: sign = +1
        # Rights subscriptions / bonus issues book as "Corp Action" with a real ticker +
        # a positive qty (the share delivery). The matching "NRO (...)" / "R (...)" rows are
        # nil-paid-rights placeholders that convert away -> never count them.
        is_nilpaid = bool(re.search(r"\b(NRO|R)\s+\(", pn))
        if is_nilpaid:
            continue                 # nil-paid rights placeholder: not a real position, skip
        if t == "Corp Action" and is_stock and qty:
            sign = +1
            # Sembcorp Marine (S51) -> renamed Seatrium -> 20:1 share consolidation that
            # retired the S51 counter into the new 5E2 counter. The "Seatrium Ltd (S51)"
            # corp action is the OLD shares being removed -> negative; "Seatrium Ltd (5E2)"
            # is the new shares (positive). Rights issues were "SembCorp Marine (S51)" (+).
            if code == "S51" and pn.startswith("Seatrium"):
                sign = -1
        qsig = (sign * abs(qty)) if (sign and is_stock and qty) else 0
        add(date=parse_date(r.get("Transaction Date")), account=fsm_acct, market="SG",
            ticker=code, asset_type=("stock" if is_stock else "cash"),
            action=action, qty_signed=qsig,
            price=r.get("Transaction Price", ""), amount=num(r.get("Product Amount")),
            currency=(r.get("Product Currency") or "").strip(),
            source="fsm/ifast_historical.csv", raw=pn)

# ---------- IBKR (legacy, NAV/MTM only — no trades) ----------
def load_ibkr_positions():
    """IBKR yearly files hold no Trades; capture MTM position rows for context."""
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "ibkr/*.csv"))):
        yr = re.search(r"(\d{4})", f).group(1)
        for row in csv.reader(open(f, encoding="utf-8-sig")):
            if row and row[0] == "Mark-to-Market Performance Summary" and len(row) > 3 and row[2] == "Data":
                out.append((yr, row))
    return out

# ---------- Moomoo (from parse_moomoo.py snapshot-diff) ----------
def load_moomoo():
    p = os.path.join(os.path.dirname(__file__), "moomoo_events.csv")
    if not os.path.exists(p): return
    for r in csv.DictReader(open(p)):
        add(date=r["date"], account="Moomoo", market=r["market"],
            ticker=canon(norm_ticker(r["ticker"], r["market"])),
            asset_type="stock", action=r["action"], qty_signed=float(r["qty_signed"]),
            price=r.get("price", ""), amount=num(r.get("amount")) if r.get("amount") else "",
            source=r["source"], raw=r["raw"])

# ---------- CDP (from parse_cdp.py snapshot-diff — authoritative custody) ----------
def load_cdp():
    p = os.path.join(os.path.dirname(__file__), "cdp_events.csv")
    if not os.path.exists(p): return
    for r in csv.DictReader(open(p)):
        code = r["code"] or r["name"]
        add(date=r["date"], account="CDP", market="SG",
            ticker=canon(code.upper()), asset_type="stock", action=r["action"],
            qty_signed=float(r["qty_signed"]), source="cdp-statements (pdf)", raw=r["name"])

# ---------- Endowus (CPF/SRS/Cash funds — from parse_endowus.py snapshot-diff) ----------
ENDOWUS_BUCKET = {"CPF OA": "CPF", "CPF SA": "CPF", "SRS": "SRS", "Cash": "Tiger Prime"}
def load_endowus():
    p = os.path.join(os.path.dirname(__file__), "endowus_events.csv")
    if not os.path.exists(p): return
    for r in csv.DictReader(open(p)):
        acct = ENDOWUS_BUCKET.get(r["src"], "CPF")
        add(date=r["date"], account=acct, market="SG", ticker="0P0001OOJG",
            asset_type="fund", action=r["action"], qty_signed=float(r["qty_signed"]),
            price=r.get("price", ""), amount=r.get("amount", ""),
            currency="SGD", source="endowus (pdf)", raw=r["fund"])

# ---------- synthesize missing transfer-in legs ----------
REAL_ACCTS = {"Tiger Prime", "Tiger Cash Boost", "Moomoo", "FSM", "CDP", "CPF", "SRS"}
def synthesize_transfer_ins():
    """Inter-broker custody moves (e.g. CDP -> FSM) were logged only on the sending
    side as `transfer_out`; the receiving broker recorded only the later sale. That
    leaves the receiver with an impossible negative position — shares it sold but
    never acquired. Where a real account nets negative for a ticker AND a matching
    `transfer_out` of the same ticker+qty exists elsewhere, inject the missing
    `transfer_in` on the receiver so both legs net to zero. This records the real
    custody move instead of leaving a phantom short."""
    net = defaultdict(float)
    for r in LEDGER:
        if r["asset_type"] in ("stock", "fund") and r["ticker"]:
            net[(r["account"], canon(r["ticker"]))] += float(r["qty_signed"] or 0)
    def is_out(a): return "transfer_out" in a or "transfer out" in a
    outs = [r for r in LEDGER if r["asset_type"] == "stock" and r["ticker"] and is_out(r["action"])]
    used = [False] * len(outs)
    for (acct, tk), q in sorted(net.items()):
        if q >= -1e-6 or acct not in REAL_ACCTS:
            continue
        need = -q                                   # shares the receiver is short
        mi = next((i for i, o in enumerate(outs) if not used[i]
                   and canon(o["ticker"]) == tk
                   and abs(abs(float(o["qty_signed"] or 0)) - need) < 1e-6), None)
        if mi is None:
            continue
        used[mi] = True; m = outs[mi]
        add(date=m["date"], account=acct, market=m["market"] or "SG", ticker=tk,
            asset_type="stock", action="transfer_in", qty_signed=need,
            source="synthesized (custody move)",
            raw=f"transfer-in leg of {m['account']} {m['raw']}")
        print(f"  synthesized transfer_in: {acct} {tk} +{need:g} (from {m['account']} {m['date']})")

# ---------- reconcile inter-broker stock transfers ----------
def reconcile_transfer_amounts():
    """Inter-broker custody move conserves cost as well as shares. The receiving
    broker (FSM) stamps the transfer-in at market value on the move date, which
    disagrees with the sending record's cost basis. Carry cost basis across so both
    legs show the same amount. Stock legs only — FX cash transfers (no ticker) are
    genuine currency conversions and keep their differing amounts."""
    def is_in(a):  return "transfer in" in a or a == "transfer_in"
    def is_out(a): return "transfer_out" in a or "transfer out" in a
    outs = [r for r in LEDGER if r["asset_type"] == "stock" and r["ticker"]
            and is_out(r["action"]) and str(r["amount"]).strip()]
    for i in LEDGER:
        if not (i["asset_type"] == "stock" and i["ticker"] and is_in(i["action"])):
            continue
        qi = abs(float(i["qty_signed"] or 0))
        m = next((o for o in outs
                  if canon(o["ticker"]) == canon(i["ticker"])
                  and abs(abs(float(o["qty_signed"] or 0)) - qi) < 1e-6), None)
        if m and i["amount"] != m["amount"]:
            print(f"  transfer cost carried: {i['ticker']} {i['amount']} -> {m['amount']}")
            i["amount"] = m["amount"]
            i["price"]  = m["price"]   # keep price x qty consistent (avg cost)

# ---------- run ----------
load_simple(); load_tiger(); load_fsm(); load_moomoo(); load_cdp(); load_endowus()
synthesize_transfer_ins()
reconcile_transfer_amounts()
LEDGER.sort(key=lambda r: (str(r["date"]), r["account"], r["ticker"]))

# write ledger.csv
cols = ["date","account","market","ticker","asset_type","action","qty_signed",
        "price","amount","currency","fees","source","raw"]
out = os.path.join(os.path.dirname(__file__), "ledger.csv")
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in LEDGER: w.writerow(r)
print(f"ledger rows: {len(LEDGER)} -> {out}")

# coverage / file inventory
print("\n=== SOURCE COVERAGE ===")
src = defaultdict(int)
for r in LEDGER: src[r["source"]] += 1
for k in sorted(src): print(f"{src[k]:5}  {k}")
