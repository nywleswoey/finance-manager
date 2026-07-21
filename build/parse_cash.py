"""Parse bank + credit-card statements into one normalized spending ledger.

Sources (scope: 2025-01 onward):
  - DBS consolidated bank statement  (data/dbs-consolidated-statements/dbs_2025*.pdf, 2026*)
      pdftotext -layout; only the DBS Multiplier (current/savings) account has a
      Withdrawal/Deposit transaction table. Direction is derived from the running
      balance delta (column-position independent, self-correcting).
  - Trust credit card                (data/trust-cc/2025*..2026*.pdf)
      pdftotext -layout; dates are "DD Mon" with the year inferred from the statement
      cycle. Credits are shown with a leading "+".
  - HSBC Live+ credit card           (build/hsbc_extracted.csv)
      scanned PDFs -> Claude-vision extracted to CSV (see build/hsbc_extracted.csv).
      Credits carry a "CR" flag.

Output: build/cash_ledger_raw.csv  (raw, pre-classification). amount_sgd is SIGNED:
negative = outflow/spend candidate, positive = inflow. classify_cash.py enriches it.

Run:  PYTHONPATH=. .venv/bin/python build/parse_cash.py
"""
import csv
import datetime as dt
import glob
import os
import re
import unicodedata

from _pdf import raw_text
from _csvout import write_csv
from _dates import try_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "cash_ledger_raw.csv")
HSBC_CSV = os.path.join(ROOT, "build", "hsbc_extracted.csv")
DBS_CC_DIR = os.path.join(ROOT, "data", "dbs-cc")
DBS_CC_CARD = "5520380059464418"  # the itemised DBS/POSB Mastercard (last8 5946-4418)
START = dt.date(2025, 1, 1)

COLS = ["source", "account_label", "txn_date", "post_date", "description", "merchant",
        "amount_sgd", "fcy_amount", "fcy_currency", "direction", "source_file", "raw"]

MONEY = re.compile(r"[+-]?[\d,]+\.\d{2}")
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def money(s):
    return float(str(s).replace(",", "").replace("+", "").strip())


def _num(s):
    s = str(s or "").replace(",", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _pdate(s):
    return try_date(s, ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"))


def pdftext(path):
    # NFKC folds typographic ligatures (Netﬂix -> Netflix) so keyword matching works
    return unicodedata.normalize("NFKC", raw_text(path))


def row(**kw):
    r = {c: "" for c in COLS}
    r.update(kw)
    return r


# ----------------------------------------------------------------- DBS bank
DBS_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s+(.*)$")
# continuation lines that are page furniture, not transaction detail
DBS_NOISE = re.compile(
    r"(SG\d{8}|PDS_MMCON|Transaction Details|Account Summary|Balance (Brought|Carried)"
    r"|^Date\s+Description|Page \d|DBS Multiplier|CURRENCY:|Co\. Reg|GST Reg|^[ws]$|^\d{5,6}[A-Z]$)")


def _name_from(detail):
    """Best merchant key from the joined continuation lines."""
    m = re.search(r"TO\s*:\s*(.+)", detail)
    if m:
        return m.group(1).strip()
    # NETS QR PAYMENT <id> TO: X already handled above; else first meaningful chunk
    return detail.split("  ")[0].strip()[:120]


def parse_dbs():
    rows = []
    files = sorted(glob.glob(os.path.join(ROOT, "data", "dbs-consolidated-statements", "dbs_*.pdf")))
    for path in files:
        stem = os.path.basename(path)
        ym = re.search(r"dbs_(\d{4})(\d{2})", stem)
        if not ym or dt.date(int(ym.group(1)), int(ym.group(2)), 1) < START.replace(day=1):
            continue
        src = os.path.relpath(path, ROOT)
        in_multiplier = False
        capturing = False
        running = None
        cur = None  # current transaction being assembled
        for raw_line in pdftext(path).splitlines():
            line = raw_line.strip()
            if "DBS Multiplier Account" in line:
                in_multiplier = True
            elif "CPF Investment Account" in line or "Supplementary Retirement" in line:
                in_multiplier = False
            if "Balance Brought Forward" in line and in_multiplier:
                nums = MONEY.findall(line)
                if nums:
                    running = money(nums[-1])
                capturing = True
                continue
            if "Balance Carried Forward" in line:
                if cur:
                    rows.append(_dbs_finish(cur, src))
                    cur = None
                capturing = False
                continue
            if not (capturing and in_multiplier):
                continue
            m = DBS_DATE.match(line)
            if m and MONEY.search(line):
                # flush previous
                if cur:
                    rows.append(_dbs_finish(cur, src))
                d, mo, y, rest = m.group(1), m.group(2), m.group(3), m.group(4)
                nums = MONEY.findall(line)
                bal = money(nums[-1])
                delta = bal - running if running is not None else 0.0
                running = bal
                txntype = MONEY.split(rest)[0].strip()
                cur = dict(date=dt.date(int(y), int(mo), int(d)), txntype=txntype,
                           amount=round(delta, 2), detail=[])
            elif cur is not None and not DBS_NOISE.search(line) and line:
                cur["detail"].append(line)
        if cur:
            rows.append(_dbs_finish(cur, src))
            cur = None
    return [r for r in rows if r]


def _dbs_finish(cur, src):
    detail = "  ".join(cur["detail"]).strip()
    amt = cur["amount"]
    if amt == 0:
        return None
    desc = (cur["txntype"] + (" | " + detail if detail else "")).strip()
    merchant = _name_from(detail) or cur["txntype"]
    return row(source="dbs", account_label="DBS", txn_date=cur["date"].isoformat(),
               post_date=cur["date"].isoformat(), description=desc[:500], merchant=merchant,
               amount_sgd=f"{amt:.2f}", direction="debit" if amt < 0 else "credit",
               source_file=src, raw=(cur["txntype"] + " || " + detail)[:1000])


# ----------------------------------------------------------------- Trust card
TRUST_CYCLE = re.compile(r"(\d{1,2})\s+(\w{3})\s+(\d{4})\s*[-–]\s*(\d{1,2})\s+(\w{3})\s+(\d{4})")
TRUST_ROW = re.compile(r"^(\d{1,2})\s+(\w{3})\s+(\d{1,2})\s+(\w{3})\s+(.+)$")
# page furniture / headers — never a merchant; reset the pending-merchant buffer
TRUST_NOISE = ("page ", "trust bank", "gst reg", "transaction", "posting date",
               "description", "amount in", "important", "activity summary", "statement",
               "hello", "for viewing", "minimum amount", "previous balance",
               "outstanding balance")
TRUST_SUMMARY = ("previous balance", "outstanding balance", "statement balance",
                 "minimum amount", "total ")


def _year_for(day, mon, start, end):
    for y in (start.year, end.year):
        try:
            cand = dt.date(y, MONTHS[mon], day)
        except (ValueError, KeyError):
            continue
        if start - dt.timedelta(days=3) <= cand <= end + dt.timedelta(days=3):
            return cand
    try:
        return dt.date(start.year, MONTHS[mon], day)
    except (ValueError, KeyError):
        return None


def parse_trust():
    rows = []
    files = sorted(glob.glob(os.path.join(ROOT, "data", "trust-cc", "*.pdf")))
    for path in files:
        src = os.path.relpath(path, ROOT)
        text = pdftext(path)
        cyc = TRUST_CYCLE.search(text)
        if not cyc:
            continue
        start = dt.date(int(cyc.group(3)), MONTHS[cyc.group(2)], int(cyc.group(1)))
        end = dt.date(int(cyc.group(6)), MONTHS[cyc.group(5)], int(cyc.group(4)))
        if end < START:
            continue
        cur = None
        pending = None  # a long merchant name printed on the line ABOVE its date+amount
        for line in text.splitlines():
            stripped = line.strip()
            m = TRUST_ROW.match(stripped)
            if m and MONEY.search(stripped):
                if cur:
                    rows.append(cur)
                    cur = None
                td, tm, pd_, pm, rest = m.groups()
                desc = MONEY.split(rest)[0].strip()
                low = desc.lower()
                # summary lines ("... Total outstanding balance 804.72") also lead with
                # twin "DD Mon DD Mon" — drop them
                if any(k in low for k in TRUST_SUMMARY):
                    pending = None
                    continue
                nums = MONEY.findall(rest)
                is_credit = "+" in nums[-1] or "+" in rest
                sgd = money(nums[-1])
                fcy = money(nums[-2]) if len(nums) >= 2 else ""
                txn_d = _year_for(int(td), tm, start, end)
                post_d = _year_for(int(pd_), pm, start, end)
                amt = sgd if is_credit else -sgd
                # inline merchant, else the wrapped one from the preceding line
                merch = desc or pending or "(unknown merchant)"
                pending = None
                cur = row(source="trust", account_label="Trust",
                          txn_date=txn_d.isoformat() if txn_d else "",
                          post_date=post_d.isoformat() if post_d else "",
                          description=merch, merchant=merch,
                          amount_sgd=f"{amt:.2f}",
                          fcy_amount=f"{fcy:.2f}" if fcy != "" else "",
                          direction="credit" if is_credit else "debit",
                          source_file=src, raw=stripped[:1000])
            elif stripped and not MONEY.search(stripped):
                # a bare text line: page furniture (skip) or a wrapped merchant name for
                # the NEXT transaction (buffer it). "+<digits> CC" country detail -> ignore.
                low = stripped.lower()
                if any(kw in low for kw in TRUST_NOISE) or stripped.startswith("+"):
                    pending = None
                elif re.search(r"[A-Za-z]", stripped):
                    pending = stripped[:120]
        if cur:
            rows.append(cur)
    return [r for r in rows if r and r["txn_date"]]


# ----------------------------------------------------------------- HSBC card (vision CSV)
def parse_hsbc():
    rows = []
    if not os.path.exists(HSBC_CSV):
        return rows
    for r in csv.DictReader(open(HSBC_CSV)):
        is_credit = r["cr_flag"].strip().upper() == "CR"
        sgd = money(r["amount_sgd"])
        amt = sgd if is_credit else -sgd
        desc = r["description"].strip()
        rows.append(row(source="hsbc", account_label="HSBC Live+",
                        txn_date=r["tran_date"], post_date=r["post_date"],
                        description=desc, merchant=desc, amount_sgd=f"{amt:.2f}",
                        direction="credit" if is_credit else "debit",
                        source_file=r["source_file"], raw=desc))
    return rows


# ----------------------------------------------------------------- DBS credit card (CSV export)
def _clean_cc_merchant(d):
    d = re.sub(r"-MP\d+$", "", d)                       # instalment-plan suffix
    d = re.sub(r"\s+(SINGAPORE\s+)?SGP$", "", d)
    d = re.sub(r"\s+SINGAPORE(\s+\d+)?$", "", d)
    return d.strip()


def parse_dbs_cc():
    """DBS/POSB Mastercard CSV exports. Returns (rows, payment_amounts).

    Signed netting: Debit -> outflow (-), Credit -> offset (+). ADJUSTMENT/REFUND credits
    net against the matching purchase (instalment plans book the purchase then reverse it,
    charging it back monthly). PAYMENT rows (the card bill) are NOT emitted — their amounts
    are returned so the DBS bank-side bill-payment can be suppressed (no double-count).
    """
    rows, closes = [], []
    seen = set()  # statement exports overlap / get duplicated -> collapse identical lines
    for path in sorted(glob.glob(os.path.join(DBS_CC_DIR, "*.csv"))):
        src = os.path.relpath(path, ROOT)
        started = False
        file_dates = []
        for rec in csv.reader(open(path, newline="")):
            if not rec:
                continue
            if rec[0].strip() == "Transaction Date":
                started = True
                continue
            if not started or len(rec) < 8:
                continue
            tdate, pdate_, desc, ttype, _pay, _status, debit, credit = rec[:8]
            dk = (tdate, pdate_, desc, ttype, debit, credit)
            if dk in seen:                                 # same txn across overlapping files
                continue
            seen.add(dk)
            d = _pdate(tdate)                              # "23 Feb 2026"
            if not d:
                continue
            file_dates.append(d)
            deb, cr = _num(debit), _num(credit)
            tt = ttype.strip().upper()
            if tt == "PAYMENT":                            # card bill settlement -> not spend
                continue
            # instalment mechanics: a purchase is reversed (ADJUSTMENT) then re-charged
            # monthly (INSTALMENT/MPPP). Keep only the ORIGINAL purchase -> drop both, so
            # the spend is counted once, in full, against the real merchant.
            if tt in ("ADJUSTMENT OF INSTALMENT PLANS & LOANS", "INSTALMENT PLANS & LOANS"):
                continue
            amt = round(cr - deb, 2)                       # +offset / -spend
            if amt == 0:
                continue
            merch = _clean_cc_merchant(desc)
            rows.append(row(source="dbs-cc", account_label="DBS Card 5946",
                            txn_date=d.isoformat(), post_date=(_pdate(pdate_) or d).isoformat(),
                            description=f"{merch} | {ttype.strip()}", merchant=merch,
                            amount_sgd=f"{amt:.2f}",
                            direction="credit" if amt > 0 else "debit",
                            source_file=src, raw=f"{desc} || {ttype.strip()}"[:1000]))
        if file_dates:
            closes.append(max(file_dates))                 # this statement's closing date
    return _cancel_reversals(rows), closes


def _cancel_reversals(rows):
    """Cancel charge+reversal pairs: a debit and a credit on the same merchant for the same
    amount (e.g. an annual fee + its waiver, a GST charge + reversal, a full refund) net to
    nothing — drop BOTH so neither counts. Partial refunds (no equal-and-opposite debit)
    stay as an offsetting credit."""
    from collections import defaultdict
    debits = defaultdict(list)
    for i, r in enumerate(rows):
        a = float(r["amount_sgd"])
        if a < 0:
            debits[(r["merchant"], round(-a, 2))].append(i)
    drop = set()
    for i, r in enumerate(rows):
        a = float(r["amount_sgd"])
        if a > 0:
            bucket = debits.get((r["merchant"], round(a, 2)))
            if bucket:
                drop.add(i)
                drop.add(bucket.pop())
    return [r for k, r in enumerate(rows) if k not in drop]


def _cc_windows(closes):
    """One payment window per card statement: its bill lands in the bank ~5-45 days after
    the statement closes. Per-statement (not a single continuous span) so MISSING months
    leave a gap — their bank lump is kept, not wrongly suppressed."""
    return [(c + dt.timedelta(days=5), c + dt.timedelta(days=45)) for c in set(closes)]


def _is_suppressed_cc_bill(r, windows):
    """Drop the DBS bank bill-payment that settles an itemised card statement (card 59464418
    and its duplicate 'DBS CARD CENTRE' GIRO row) — its line items replace it. Only payments
    falling in a covered statement's window are dropped; the other card (56013291) and
    months without a statement stay as a lump (no lost spend)."""
    if r["source"] != "dbs":
        return False
    raw = r["raw"]
    if DBS_CC_CARD not in raw and "DBS CARD CENTRE" not in raw:
        return False
    d = _pdate(r["txn_date"])
    return d is not None and any(s <= d <= e for s, e in windows)


def main():
    cc_rows, closes = parse_dbs_cc()
    windows = _cc_windows(closes)
    rows = parse_dbs() + parse_trust() + parse_hsbc() + cc_rows
    rows = [r for r in rows if not _is_suppressed_cc_bill(r, windows)]
    rows = [r for r in rows if r["txn_date"] >= START.isoformat()]
    rows.sort(key=lambda r: (r["txn_date"], r["source"]))
    write_csv(OUT, COLS, rows)
    by_src = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"cash_ledger_raw: {len(rows)} rows -> {os.path.relpath(OUT, ROOT)}  {by_src}")


if __name__ == "__main__":
    main()
