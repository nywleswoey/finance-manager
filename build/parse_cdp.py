#!/usr/bin/env python3
"""Parse CDP monthly statement PDFs -> holdings snapshots -> share-movement timeline.

CDP statements are the authoritative custody record (no fees). Two layouts:
  2017-2018: "Securities Holdings as at <date>"  cols: Free / Available / Balance / Price / MktVal
  2019+    : "Securities Holdings"               cols: Free / Blocked   / Balance / Price / MktVal
Both have a NAME then Free, (NIL|qty), Balance, price, mktval. Snapshot-diff the
Balance per security across months to recover every buy/sell/transfer.
"""
import glob, os, re, csv

from _pdf import raw_text

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "cdp-statements")

# CDP display name -> SGX code (current holdings confirmed; historical best-effort)
# CDP display name -> canonical SGX code. Renamed securities map to ONE code so the
# snapshot-diff treats a rename as continuity (no spurious sell+rebuy):
#   AIMSAMP CAP REIT == AIMS APAC REIT == O5RU
#   CROMWELL/STONEWEG European REIT (all variants) == CWBU
NAME2CODE = {
    "HOCK LIAN SENG": "J2T", "HYPHENS PHARMA": "1J5", "JUMBO": "42R",
    "OCBC BANK": "O39", "QAF": "Q01", "SASSEUR REIT": "CRPU",
    "AIMSAMP CAP REIT": "O5RU", "AIMS APAC REIT": "O5RU",
    "CENTURION": "OU8", "DBS": "D05", "GUOCOLAND": "F17", "HRNETGROUP": "CHZ",
    "SINGTEL": "Z74", "ASIAN PAY TV TR": "S7OU", "ADVANCER GLOBAL": "43Q",
    "NETLINK NBN TR": "CJLU", "RAFFLES MEDICAL": "BSL", "SOILBUILDBIZREIT": "SV3U",
    "STARHILLGBL REIT": "P40U", "TOP GLOVE": "BVA",
    "STONEWEG EUTRUST": "CWBU", "STONEWEG REIT EU": "CWBU",
    "CROMWELL REIT EU": "CWBU", "CROMWELLREIT EUR": "CWBU",
    "EAGLE HTRUST USD": "LIW", "MANULIFEREIT USD": "BTOU",
    "NORDIC": "MR7", "SILVERLAKE AXIS": "5CP", "UMS": "558",
    "ACCORDIA GOLF TR": "ADQU", "ACCORDIA GOLF TR (SUSP)": "ADQU",
    "ASTREAVIB310318": "ASTREA6B",
}
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
    return NAME2CODE.get(name, re.sub(r"[^A-Z0-9]", "", name.upper())[:8] or "?")

def main():
    snaps = {}; label = {}
    for p in sorted(glob.glob(os.path.join(DATA, "*.pdf"))):
        ym, hold = parse(p)
        if not hold: continue
        # collapse names -> canonical code, summing same-code rows within the month
        bycode = {}
        for name, bal in hold.items():
            c = code_of(name); bycode[c] = bycode.get(c, 0) + bal; label[c] = name
        snaps[ym] = bycode
    months = sorted(snaps)
    codes = sorted({c for h in snaps.values() for c in h})
    unmapped = sorted({c for c in codes if c not in NAME2CODE.values()})
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
    if unmapped: print("UNMAPPED codes (review):", unmapped)
    print("\n=== CDP timeline (snapshot-diff, by canonical code) ===")
    for mo, c, act, q in ev:
        print(f"  {mo}  {c:8} {label.get(c,''):20} {act:18} {q:>+9.0f}")
    # latest snapshot vs Holdings.md CDP (SET==CWBU)
    last = months[-1]
    HOLD = {"J2T":700,"1J5":3000,"42R":3000,"O39":919,"Q01":17000,"CRPU":6500,"CWBU":1400}
    print(f"\n=== latest CDP snapshot ({last}) vs Holdings.md ===")
    for c in sorted(set(list(HOLD) + list(snaps[last]))):
        h, v = HOLD.get(c), snaps[last].get(c)
        print(f"  {c:8} statement={v!s:>8}  Holdings={h}  {'OK' if h==v else ('—' if h is None else 'CHECK')}")
    out = os.path.join(os.path.dirname(__file__), "cdp_events.csv")
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date","name","code","action","qty_signed"])
        for mo, c, act, q in ev:
            w.writerow([mo + "-28", label.get(c, ""), c, act, q])
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
