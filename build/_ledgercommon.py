"""Shared statement-parsing conventions used across build/ scripts (and, via
`from build._ledgercommon import ...`, the ingestion loaders).

Holds the parse-layer primitives that every statement parser reimplemented inline:
the `ALIAS`/`canon` counter-rename map, the `num` money parser, and the
`norm_ticker` symbol normaliser. Kept import-free (only stdlib `re`) so it loads
cleanly whether imported as a bare sibling (`python3 build/x.py`, build/ on
sys.path[0]) or as a package member (`-m ingestion.x`, repo root on path).
"""
import re

# Holdings.md label -> canonical SGX/exchange code used in transaction data.
# CWBU->SET: SGX counter renamed (Cromwell->Stoneweg).
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}


def canon(t):
    return ALIAS.get(t, t)


def num(s):
    """Parse a money/quantity cell to float. Strips thousands separators and `$`,
    reads `(1.23)` as -1.23, and maps blanks/`-`/`--` to 0.0. This is the
    0.0-sentinel flavour; ingestion/load.py deliberately keeps a None-sentinel
    variant for nullable DB columns (a missing price is NULL, not zero)."""
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "").replace("$", "")
    if s in ("", "-", "--"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


# ---------- amount sign ----------
# The ledger's `amount` is investor cash flow: a buy is money out (negative), a sell is
# money in (positive). The SG broker CSVs already write it that way ("($9,281.18)" for a
# buy), and portfolio.performance.cdp_cost reads them on exactly that assumption. The two
# statement exports below each mean something *else* by their money column, so they are
# normalised here rather than copied through.

def trade_cash_flow(amount, qty_signed):
    """Tiger's flex `Amount` is qty x price, so it carries the *position's* sign: positive
    on a buy, negative on a sell — the inverse of cash flow. Flip it: shares in means money
    out. A zero quantity leaves the figure alone (nothing changed hands)."""
    if not qty_signed:
        return amount
    return -abs(amount) if qty_signed > 0 else abs(amount)


# iFast writes a magnitude in "Product Amount" and puts the direction in *which* of its two
# amount columns is filled; an unfilled one is blank or a bare dash.
FSM_NO_AMOUNT = ("", "-", "--")


def fsm_amount_is_into_product(row):
    """True when iFast booked this row as money going *into* the product ("Investment
    Amount"), false when it came back out ("Redemption Amount"). Exactly one is ever
    filled. A literal "0" counts as filled — nil-paid rights rows carry a real zero."""
    return str(row.get("Investment Amount") or "").strip() not in FSM_NO_AMOUNT


def fsm_cash_flow(amount, into_product, is_cash_leg):
    """Turn an iFast magnitude into cash flow. The polarity inverts between the two legs
    iFast books for one trade: investing in the *stock* spends cash, while that same money
    landing in the *cash account* is cash received."""
    into_cash = into_product if is_cash_leg else not into_product
    return abs(amount) if into_cash else -abs(amount)


def norm_ticker(sym, market):
    """Normalise a display symbol to its bare exchange code: pull a trailing
    "(00823)" out of "Link Reit (00823)", drop a ".SI/.US/.HK" suffix, zero-pad
    HK numeric tickers to 5 digits, upper-case. Does NOT apply `canon` — compose
    `canon(norm_ticker(...))` when the canonical rename is also wanted."""
    if not sym:
        return ""
    sym = sym.strip()
    m = re.search(r"\(([^)]+)\)\s*$", sym)          # "Link Reit (00823)" -> 00823
    if m:
        sym = m.group(1).strip()
    sym = re.sub(r"\.(SI|US|HK)$", "", sym, flags=re.I)
    if market == "HK" and re.fullmatch(r"\d+", sym):
        sym = sym.zfill(5)
    return sym.upper()


# transfer-leg action predicates (both underscore and space spellings occur)
def is_transfer_out(a): return "transfer_out" in a or "transfer out" in a
def is_transfer_in(a):  return "transfer in" in a or a == "transfer_in"
