"""Shared statement-parsing conventions used across build/ scripts (and, via
`from build._ledgercommon import ...`, the ingestion loaders).

Holds the parse-layer primitives that every statement parser reimplemented inline:
the `ALIAS`/`canon` counter-rename map, the `num` money parser, the
`norm_ticker` symbol normaliser, `name_to_ticker` (display name to ticker, from
symbols.csv), `cdp_dividend_ticker`, `market_of` (ticker shape to market), `MARKET_CCY`, and
`TIGER_FEE_COLS`. Stdlib only, so it loads cleanly whether imported as a bare
sibling (`python3 build/x.py`, build/ on sys.path[0]) or as a package member
(`-m ingestion.x`, repo root on path).
"""
import csv
import os
import re

# Holdings.md label -> canonical SGX/exchange code used in transaction data.
# CWBU->SET: SGX counter renamed (Cromwell->Stoneweg).
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}


def canon(t):
    return ALIAS.get(t, t)


# Market code -> the currency that market's statements quote. MY is in the map
# because FSM books Bursa trades in MYR; a market this does not name has no currency.
MARKET_CCY = {"SG": "SGD", "US": "USD", "HK": "HKD", "MY": "MYR"}

# Per-trade fee columns in the Tiger flex Trades section. Summed by name, so a
# file whose columns shift (2020 has 54, later files 53) still adds the same fees.
TIGER_FEE_COLS = (
    "Transaction Fee", "Other Tripartite fees", "Settlement Fee", "SEC Fee",
    "Option Regulatory Fee", "Stamp Duty", "Transaction Levy", "Clearing Fee",
    "Trading Activity Fee", "Exchange Fee", "Future Regulatory Fee", "Commission",
    "Platform Fee", "Option Settlement Fee", "Subscription Fee", "Redemption Fee",
    "Switching Fee", "PH Stock Transaction Tax", "Tax Service Fee", "AFRC Transaction Levy",
    "Trading Tariff", "Brokerage fee", "Handing Fee", "Securities Management Fee",
    "Transfer Fees (CSDC)", "Transfer Fees (HKSCC)", "Stamp Duty On Stock Borrowing",
    "Consolidated Audit Trail Fee", "Processing Fee", "CM DA SI Fee", "DVP SI Fee",
    "IPO Transaction Fee", "IPO Process Fee", "Ipo Settle Fee", "IPO Channel Fee", "GST",
)


def market_of(sym):
    """Market implied by a ticker's shape, when the row itself did not say.

    `.SI` is SG. An all-digit code, including one pulled out of a trailing
    `(00823)`, is HK. A letters-and-dots code (`AAPL`, `BRK.B`), or a bare
    display name with no code (`Apple Inc`), is US. Anything
    else (`D05`, `C38U`, `9CI`) is SG — an SGX counter that arrived without `.SI`.

    A letters-only SGX code (`SET`) is indistinguishable from a US ticker by
    shape. A caller that already has a market (the ledger, an option leg) keeps
    that and does not consult this.
    """
    s = "" if sym is None else str(sym).strip()
    if re.search(r"\.SI\b", s, re.I):
        return "SG"
    inner = s.split("(")[-1].strip(") ").strip()
    code = re.sub(r"\.(US|HK)$", "", inner or s, flags=re.I).strip()
    if code.isdigit():
        return "HK"
    if re.fullmatch(r"[A-Za-z. ]+", code):
        return "US"
    return "SG"


_NAME_TO_TICKER = None


def _symbol_names():
    """display name (casefolded) -> canonical ticker, from symbols.csv `names`."""
    global _NAME_TO_TICKER
    if _NAME_TO_TICKER is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "symbols.csv")
        out = {}
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                for a in (r.get("names") or "").split(";"):
                    a = a.strip()
                    if not a or "(label" in a:
                        continue
                    out.setdefault(a.casefold(), r["canonical"])
        _NAME_TO_TICKER = out
    return _NAME_TO_TICKER


def name_to_ticker(name):
    """Canonical ticker for a statement display name, read from symbols.csv.

    Case-insensitive. A name the CSV does not carry returns None; callers fall
    back only for those. `(label alias)` cells are codes, not names.
    """
    if not name:
        return None
    return _symbol_names().get(str(name).strip().casefold())


# CDP dividend-sheet names that are booked as cash dividends. The sheet also
# carries T-bills and holdings a broker statement already books; those stay
# skipped even though symbols.csv can resolve them.
CDP_DIVIDEND_NAMES = frozenset({
    "AIMS APAC Reit", "Accordia Golf Tr", "Advancer Global", "Asian Pay Tv Tr",
    "CapitaLandInvest", "Centurion", "Capitaland Integrated Commercial Trust",
    "Comfort Delgro", "DBS", "Eagle Htrust USD", "GuocoLand", "HRnetGroup",
    "Hock Lian Seng", "Hongkong Land Holdings", "Hyphens Pharma", "IREIT Global",
    "Jumbo", "Keppel Pacific Oak US Reit", "Manulife US Reit", "Mapletree PanAsia Com Tr",
    "Nordic", "OCBC", "QAF", "SBS Transit", "Sasseur Reit", "Sembcorp Industries",
    "Silverlake Axis", "SingTel", "Soibuild Biz Reit", "Starhill Global Reit",
    "Stoneweg European Trust EUR", "Top Glove", "UMS", "Wilmar",
})


def cdp_dividend_ticker(name):
    """Ticker for a CDP dividend-sheet name, or None when the row is not booked."""
    return name_to_ticker(name) if name in CDP_DIVIDEND_NAMES else None


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
