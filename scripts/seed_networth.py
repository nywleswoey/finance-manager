"""Seed the fixed net-worth catalogue (nw_item). Idempotent: upserts by `code`.

Run: PYTHONPATH=. .venv/bin/python scripts/seed_networth.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import select

from portfolio.db import SessionLocal
from portfolio.models import NwItem

# code, label, kind, ccy, liquid, housing, cpf
CATALOGUE = [
    ("posb",              "POSB Shared Account",            "asset",     "SGD", True,  False, False),
    ("dbs_multiplier",    "DBS Multiplier",                 "asset",     "SGD", True,  False, False),
    ("srs",               "SRS Account",                    "asset",     "SGD", False, False, False),
    ("tiger_hkd",         "Tiger HKD Cash",                 "asset",     "HKD", True,  False, False),
    ("tiger_sgd",         "Tiger SGD Cash",                 "asset",     "SGD", True,  False, False),
    ("tiger_usd",         "Tiger USD Cash",                 "asset",     "USD", True,  False, False),
    ("tiger_vault",       "Tiger Vault",                    "asset",     "SGD", True,  False, False),
    ("ibkr_sgd",          "IBKR SGD Cash",                  "asset",     "SGD", True,  False, False),
    ("cpf_oa",            "CPF OA",                         "asset",     "SGD", False, False, True),
    ("cpf_sa",            "CPF SA",                         "asset",     "SGD", False, False, True),
    ("cpf_ma",            "CPF MA",                         "asset",     "SGD", False, False, True),
    ("hdb",               "Tampines HDB",                   "asset",     "SGD", False, True,  False),
    ("home_loan",         "CPF Home Loan",                  "liability", "SGD", False, True,  False),
    ("home_loan_accrued", "CPF Home Loan Accrued Interest", "liability", "SGD", False, True,  False),
]


def main():
    s = SessionLocal()
    for order, (code, label, kind, ccy, liq, hou, cpf) in enumerate(CATALOGUE):
        row = s.scalar(select(NwItem).where(NwItem.code == code))
        if row is None:
            row = NwItem(code=code)
            s.add(row)
        row.label = label
        row.kind = kind
        row.currency_default = ccy
        row.is_liquid = liq
        row.is_housing = hou
        row.is_cpf = cpf
        row.sort_order = order
        row.active = True
    s.commit()
    n = s.query(NwItem).count()
    s.close()
    print(f"seeded nw_item: {len(CATALOGUE)} upserted, {n} total")


if __name__ == "__main__":
    main()
