"""Seed reference data: accounts, securities, security_alias, corporate_action.

Sources:
  build/ledger.csv  -> canonical ticker -> market (authoritative market mapping)
  symbols.csv       -> aliases (names + variant codes) per canonical
  curated below     -> display names, asset types, corporate actions (renames/splits)
Idempotent: upserts by natural key, safe to re-run.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import func, select

from portfolio.db import SessionLocal
from portfolio.models import Account, CorporateAction, Security, SecurityAlias

ROOT = os.path.dirname(os.path.dirname(__file__))

ACCOUNTS = [
    ("Tiger Prime", "Tiger Brokers", "cash"),
    ("Tiger Cash Boost", "Tiger Brokers", "cash"),
    ("Moomoo", "Moomoo Financial SG", "cash"),
    ("FSM", "iFast / FSMOne", "cash"),
    ("CDP", "SGX CDP", "cash"),
    ("CPF", "CPF Investment Scheme", "cpf"),
    ("SRS", "SRS", "srs"),
    ("IBKR", "Interactive Brokers", "cash"),   # options only (IBKR flex exports carry no trades)
]

# curated display names + asset types (rest inferred)
NAME = {
    "SET": "Stoneweg European Reit", "5E2": "Seatrium", "S51": "Seatrium (old S51)",
    "0P0001OOJG": "Amundi Prime USA Fund",
}
ASSET_TYPE = {"0P0001OOJG": "fund", "0P00006FYT": "fund"}
REITS = {"O5RU", "C38U", "UD1U", "N2IU", "CRPU", "SET", "CWBU", "BTOU", "S7OU", "P40U",
         "SV3U", "ADQU", "HMN", "9CI", "CMOU", "LIW", "H78", "CJLU"}
CCY = {"US": "USD", "HK": "HKD", "SG": "SGD", "MY": "MYR"}

# ticker code changes / restructures (PLAN.md)
CORP_ACTIONS = [
    ("rename", "CWBU", "SET", None, None, "Cromwell European REIT -> Stoneweg European REIT (SGX counter changed)"),
    ("consolidation", "S51", "5E2", 1, 20, "Sembcorp Marine -> Seatrium 20:1 share consolidation"),
    ("split", "C31", "9CI", None, None, "CapitaLand restructuring 2021 -> CapitaLand Investment (9CI)"),
    ("distribution", "C31", "C38U", None, None, "CapitaLand restructuring 2021 -> CICT (C38U) in-specie distribution"),
    ("switch", "0P00006FYT", "0P0001OOJG", None, None, "CPF fund switch Apr-2023: LionGlobal Infinity US500 -> Amundi Prime USA (proceeds reinvested; cost carries)"),
]


def is_security(t):
    return bool(t) and " " not in t and len(t) <= 24 and "CALL" not in t and "PUT" not in t

def markets_from_ledger():
    m = {}
    p = os.path.join(ROOT, "build", "ledger.csv")
    for r in csv.DictReader(open(p)):
        if r["asset_type"] in ("stock", "fund") and is_security(r["ticker"]) and r["market"]:
            m[r["ticker"]] = r["market"]
    return m


def names_from_ledger():
    """derive HK/US display names from raw broker symbols (e.g. 'LINK REIT (00823)')."""
    import re
    from collections import Counter, defaultdict
    seen = defaultdict(Counter)
    for r in csv.DictReader(open(os.path.join(ROOT, "build", "ledger.csv"))):
        if r["asset_type"] not in ("stock", "fund") or not is_security(r["ticker"]):
            continue
        raw = (r["raw"] or "").strip()
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", raw)
        nm = m.group(1) if (m and re.search(r"[A-Za-z]", m.group(1))) else raw
        nm = re.sub(r"\s+(HKD|USD|SGD|CNH)\s*$", "", nm).strip(" ,.")
        if re.search(r"[A-Za-z]", nm) and not re.fullmatch(r"\d{4}-\d\d", nm):
            seen[r["ticker"]][nm] += 1
    return {t: c.most_common(1)[0][0] for t, c in seen.items()}


def load_symbols():
    """canonical -> (set(aliases), shortest clean name)."""
    out = {}
    p = os.path.join(ROOT, "symbols.csv")
    for r in csv.DictReader(open(p)):
        c = r["canonical"]
        aliases = {a.strip() for a in r["names"].split(";") if a.strip() and "(label" not in a}
        aliases.add(r["alias_code"])
        d = out.setdefault(c, {"aliases": set(), "name": None})
        d["aliases"] |= aliases
        # a real name has a space or a lowercase letter (exclude bare codes like '1J5','O5RU')
        clean = [a for a in aliases if "Dividend" not in a and "NRO" not in a and "Lieu" not in a
                 and (" " in a or any(ch.islower() for ch in a))]
        if clean:
            cand = min(clean, key=len)
            if not d["name"] or len(cand) < len(d["name"]):
                d["name"] = cand
    return out


def upsert(session, model, by, **vals):
    obj = session.scalar(select(model).filter_by(**by))
    if obj:
        for k, v in vals.items():
            setattr(obj, k, v)
    else:
        obj = model(**by, **vals)
        session.add(obj)
    return obj


def main():
    s = SessionLocal()
    for name, broker, bucket in ACCOUNTS:
        upsert(s, Account, {"name": name}, broker=broker, funding_bucket=bucket, base_currency="SGD")

    mkt = markets_from_ledger()
    syms = load_symbols()
    raw_names = names_from_ledger()
    # union of canonicals from symbols + any ledger ticker not in symbols
    canon = set(syms) | set(mkt) | set(NAME)
    canon = {c for c in canon if is_security(c) and not c.startswith("SGXZ")}  # skip options + T-bills

    for c in sorted(canon):
        market = mkt.get(c) or ("HK" if c.isdigit() else "SG")
        name = NAME.get(c) or (syms.get(c, {}).get("name")) or raw_names.get(c) or c
        atype = ASSET_TYPE.get(c) or ("reit" if c in REITS else "stock")
        sec = upsert(s, Security, {"canonical_ticker": c},
                     name=name, market=market, asset_type=atype, currency=CCY.get(market))
        s.flush()
        aliases = syms.get(c, {}).get("aliases", set()) | {c, NAME.get(c, "")}
        for a in {a for a in aliases if a}:
            if not s.scalar(select(SecurityAlias).filter_by(alias=a)):
                s.add(SecurityAlias(security_id=sec.id, alias=a, source="seed"))

    by_ticker = {x.canonical_ticker: x for x in s.scalars(select(Security))}
    for typ, frm, to, rn, rd, note in CORP_ACTIONS:
        sec = by_ticker.get(to) or by_ticker.get(frm)
        if not s.scalar(select(CorporateAction).filter_by(from_ticker=frm, to_ticker=to)):
            s.add(CorporateAction(security_id=sec.id if sec else None, type=typ,
                                  from_ticker=frm, to_ticker=to, ratio_num=rn, ratio_den=rd, notes=note))

    s.commit()
    for label, model in (("accounts", Account), ("securities", Security),
                         ("aliases", SecurityAlias), ("corporate_actions", CorporateAction)):
        print(f"{label}: {s.scalar(select(func.count()).select_from(model))}")
    s.close()


if __name__ == "__main__":
    main()
