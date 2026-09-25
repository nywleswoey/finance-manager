#!/usr/bin/env python3
"""Parse CDP monthly statement PDFs -> holdings snapshots -> share-movement timeline.

CDP statements are the authoritative custody record (no fees). Two layouts:
  2017-2018: "Securities Holdings as at <date>"  cols: Free / Available / Balance / Price / MktVal
  2019+    : "Securities Holdings"               cols: Free / Blocked   / Balance / Price / MktVal
Both have a NAME then Free, (NIL|qty), Balance, price, mktval. Snapshot-diff the
Balance per security across months to recover every buy/sell/transfer.
"""
import glob, os, re

from _pdf import raw_text
from _csvout import write_rows
from _ledgercommon import name_to_ticker

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "cdp-statements")
ROW = re.compile(r"^\s*([A-Z0-9][A-Z0-9 &.\-/()']+?)\s+([\d,]+)\s+(NIL|[\d,]+)\s+([\d,]+)\s+[\d,]+\.\d+\s+[\d,]+\.\d+\s*$")

def f(s): return float(s.replace(",", ""))

def parse(path):
    mo = re.search(r"(\d{6})", path).group(1)
    ym = f"{mo[:4]}-{mo[4:]}"
    txt = raw_text(path)
    out = {}
    inhold = False
    for ln in txt.splitlines():
        if "Securities Holdings" in ln: inhold = True; continue
        # stay in the holdings block through the EUR/foreign sub-tables (after "TOTAL: SGD");
        # only exit at end-of-section markers.
        if inhold and re.search(r"- END -|Summary of Payments|Your Securities Account|^\s*Bonds|Portfolio Summary", ln):
            inhold = False; continue
        if not inhold: continue
        m = ROW.match(ln)
        if not m: continue
        name = m.group(1).strip()
        if name in ("Security", "Main Balance"): continue
        out[name] = f(m.group(4))           # Balance column
    return ym, out

def code_of(name):
    """Canonical ticker for a CDP statement name. symbols.csv owns the map;
    a name it does not carry falls back to a squashed code so the row is visible."""
    return name_to_ticker(name) or re.sub(r"[^A-Z0-9]", "", name.upper())[:8] or "?"

def main():
    snaps = {}; label = {}; unmapped = set()
    for p in sorted(glob.glob(os.path.join(DATA, "*.pdf"))):
        ym, hold = parse(p)
        if not hold: continue
        # collapse names -> canonical code, summing same-code rows within the month
        bycode = {}
        for name, bal in hold.items():
            c = code_of(name)
            if name_to_ticker(name) is None:
                unmapped.add(name)
            bycode[c] = bycode.get(c, 0) + bal; label[c] = name
        snaps[ym] = bycode
    months = sorted(snaps)
    codes = sorted({c for h in snaps.values() for c in h})
    unmapped = sorted(unmapped)
    # snapshot-diff per CANONICAL CODE -> events (renames are now continuous)
    ev = []
    for c in codes:
        prev = 0.0; seen = False
        for mo in months:
            if c in snaps[mo]:
                cur = snaps[mo][c]; d = cur - prev
                if not seen and cur:
                    ev.append((mo, c, "open", cur))
                elif abs(d) > 1e-9:
                    ev.append((mo, c, "buy" if d > 0 else "sell/transfer_out", d))
                prev = cur; seen = True
            elif seen and prev:                      # dropped out of holdings -> exited
                ev.append((mo, c, "sell/transfer_out", -prev)); prev = 0.0
    print(f"CDP statements: {len(months)} ({months[0]}..{months[-1]}), securities (by code): {len(codes)}")
    if unmapped: print("UNMAPPED names (review):", unmapped)
    print("\n=== CDP timeline (snapshot-diff, by canonical code) ===")
    for mo, c, act, q in ev:
        print(f"  {mo}  {c:8} {label.get(c,''):20} {act:18} {q:>+9.0f}")
    out = os.path.join(os.path.dirname(__file__), "cdp_events.csv")
    write_rows(out, ["date", "name", "code", "action", "qty_signed"],
               [[mo + "-28", label.get(c, ""), c, act, q] for mo, c, act, q in ev])
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
