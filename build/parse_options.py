"""Tiger flex option legs — the parser half of the sold-option book.

Reads the `Trades` section, asset type `Option`, of every Tiger flex statement and yields one
normalised leg per row: contract key (underlying, expiry, type, strike), quantity, price, the
summed named fee columns, Tiger's own `Realized P/L`, trade date, and whether the leg opens or
closes (`Activity Type` = OpenShort / Close; older files leave it blank, so the quantity's sign
decides: < 0 opens, > 0 closes). Reconciling legs into contracts and loading them is
ingestion/load_options.py; scripts/seed.py reads the legs to seed option-only underlyings.
"""
import datetime as dt
import os
import re

from build import tiger_flex
from build._dates import pdate
from build._ledgercommon import TIGER_FEE_COLS, num

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
# The pre-reconciled 12-col IBKR export carved from the old Tiger archive (IBKR flex files carry
# no trades, so this hand-kept file is the only record). Read by load_options and seed.py.
IBKR_SRC = os.path.join(DATA, "ibkr-options", "options.csv")
MULT = {"US": 100, "HK": 1}                  # HK contract sizes vary; default 1 (rare here)

# option symbol: bare "AMD 20210917 PUT 77.5" OR wrapped "Advanced Micro Devices (AMD ... )".
_SYM = re.compile(r"([A-Z0-9.]+)\s+(\d{8})\s+(PUT|CALL)\s+([\d.]+)")


def _und(ticker):
    """Normalise underlying to the archive's convention (HK counters carry a '.HK' suffix)."""
    t = (ticker or "").upper()
    return t[:-3] if t.endswith(".HK") else t


def _expiry(s):
    """Option expiry is 8-digit YYYYMMDD in the symbol (e.g. '20260710')."""
    try:
        return dt.datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def flex_option_legs(data_dir=DATA):
    """Yield normalised option legs from all Tiger flex statements."""
    for f, _account in tiger_flex.statements(data_dir):
        for row, g in tiger_flex.records(tiger_flex.read(f), "Trades"):
            if len(row) <= 4 or row[1] != "Option":
                continue
            sym = g("Symbol")
            if not sym.strip():                              # continuation row
                continue
            m = _SYM.search(sym)
            if not m:
                continue
            und, exp, typ, strike = m.groups()
            qty = num(g("Quantity"))
            act = g("Activity Type").strip()
            is_open = act == "OpenShort" or (act == "" and qty < 0)
            is_close = act == "Close" or (act == "" and qty > 0)
            if not (is_open or is_close):
                continue
            mkt = g("Market") or "US"
            yield dict(
                underlying=_und(und), expiry=_expiry(exp), option_type=typ.lower(),
                strike=float(strike), market=mkt, mult=MULT.get(mkt, 100),
                qty=abs(qty), price=num(g("Trade Price")),
                fees=abs(sum(num(g(n)) for n in TIGER_FEE_COLS)),   # "" -> 0.0 for a column this file lacks
                realized=num(g("Realized P/L")),
                trade_date=pdate((g("Trade Time") or "")[:10]),
                is_open=is_open,
            )
