"""The fold. `_accumulate_positions` replays the ledger into per-position events and running
totals; `fold_positions` turns those into the finished rows (verdict, CAR, XIRR, breakeven)."""
from __future__ import annotations

import logging
from collections import defaultdict

from ingestion.prices import sg_today

from ..cost_annotations import annotation_map
from ..money import convert, rate_to_sgd
from ..nullable import num, rounded
from .actions import CDP_ACCOUNT, STOCK_MOVING_LEG, classify_action
from .carry import _carry_corporate_actions, _provenance, carry_bound
from .entries import _apply_txn, _apply_units, cost_partition
from .events import UnitEvent
from .legs import is_leg
from .peak_car import legs_by_ticker, ticker_car
from .rows import _build_row, _ticker_xirr, _xirr_flows
from .verdict import _breakeven_price, _net_pl, _return_figures, net_verdict

log = logging.getLogger(__name__)


def _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations, fx=None):
    """Accumulate per-(funding_bucket, security) positions from the fold's inputs. Returns
    `(pos, meta)` — the raw accumulators and the last-seen metadata row per position.

    `fx` restates a dividend paid in a currency other than the security's into the
    security's currency, so `income` and the XIRR flow are both in one currency.

    Split out of fold_positions() so the accumulators are reachable without going through
    _build_row(): each one carries a dated `unit_events` / `cost_events` series beside the
    undated running totals, and peak capital-at-risk (#143 §9) and the dated corporate-action
    carry (§12) both replay those in date order — `ticker_car` and `_carry_leg` read them, and
    so does the ledger audit.

    `annotations` is the curated free/transferred map (portfolio.cost_annotations) the cost
    partition consults; it arrives as plain data like the corporate actions do."""
    fx = fx or {}
    # group per (bucket, security): transfers within a bucket (e.g. CDP->FSM) keep the cost
    # together, so a position transferred into FSM still carries its original CDP purchase cost.
    # the partition counters ride alongside the cost accumulators: every entering unit is added
    # to `units_in` exactly once and to exactly one condition, so the two can only disagree if
    # this loop does — which is what cost_partition's self-check watches for.
    pos = defaultdict(lambda: {"units": 0.0, "flows": [], "invested": 0.0, "proceeds": 0.0,
                                "income": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "fees": 0.0,
                                "accounts": set(), "unit_events": [], "cost_events": [],
                                "entries": [],
                                "units_in": 0.0, "costed_units": 0.0, "free_units": 0.0,
                                "unknown_units": 0.0, "pending_units": 0.0,
                                "pending_events": [], "carried_units": 0.0, "carry": None,
                                "transfer_out_units": 0.0, "cdp_units_in": 0.0,
                                "cdp_buy_qty": 0.0, "cdp_lots": []})
    meta = {}
    _unknown_actions = set()
    # an undated row is folded as if it happened `today`, while /api/return's `compute_twr`
    # drops it (`WHERE trade_date IS NOT NULL`): the two engines then disagree about it, so the
    # fallback is not allowed to fire silently. Zero-instance on the live book.
    undated = [r["canonical_ticker"] for r in txns if r["trade_date"] is None]
    undated += [f"dividend:{d['security_id']}" for d in divs if d["pay_date"] is None]
    if undated:
        log.warning("%d undated txn/dividend row(s) %s folded as dated today — /api/return "
                    "drops them instead", len(undated), sorted(set(undated)))
    for r in txns:
        k = (r["funding_bucket"], r["security_id"])
        meta[k] = r
        p = pos[k]
        qty = float(r["qty_signed"])
        p["units"] += qty
        # every row that moves units gets an event, CDP included: CDP units come from the txn
        # ledger even though their cost arrives from cdp_cost_lot below.
        p["unit_events"].append(UnitEvent(r["trade_date"] or today, qty, r["action"],
                                          r["action"] in STOCK_MOVING_LEG, r["account"]))
        p["accounts"].add(r["account"])
        kind = classify_action(r["action"], num(r["price"]))   # classified once; both folds read it
        _apply_units(p, r, kind, today, annotations)
        if r["account"] == CDP_ACCOUNT:
            continue                                   # CDP cost comes from cdp-stocks below
        unk = _apply_txn(p, r, kind, today)
        if unk is not None:
            _unknown_actions.add(unk)

    if _unknown_actions:
        log.warning("unclassified txn action(s) %s — treated as zero-cash; units may be uncosted",
                    sorted(_unknown_actions))

    # CDP cost (cdp-stocks) -> the CASH bucket position for that security, but only when that
    # position actually holds a CDP txn row (#146): a ticker held only at FSM can still have a
    # cdp_cost_lot row (H78), and attaching it there double-counts FSM's own priced buys/sells.
    # Matched at POSITION level via `accounts` (every row's account, CDP included, lands there
    # before the per-row CDP skip below) rather than per row, so a CDP txn row that aggregates
    # several trade-dated lots (LIW, S7OU, D05, J2T, Z74) still gets its full cost attached.
    sec_by_ticker = {m["canonical_ticker"]: sid for (_, sid), m in meta.items()}
    for tk, c in cdp.items():
        sid = sec_by_ticker.get(tk)
        k = ("cash", sid)
        if sid is None or k not in pos or CDP_ACCOUNT not in pos[k]["accounts"]:
            continue
        pos[k]["flows"].extend(c["flows"])
        pos[k]["invested"] += c["invested"]
        pos[k]["buy_cost"] += c["buy_cost"]
        pos[k]["buy_qty"] += c["buy_qty"]
        pos[k]["cost_events"].extend(c["cost_events"])
        pos[k]["cdp_buy_qty"] += c["buy_qty"]
        pos[k]["cdp_lots"].extend(c.get("unit_lots", ()))
        pos[k]["proceeds"] += sum(a for _, a in c["flows"] if a > 0)

    bucket_by_acct_id = {r["account_id"]: r["funding_bucket"] for r in txns}
    # a dividend lands on the (bucket, security) position its account belongs to. One with no
    # such position has nowhere to go, but `dividends.annual()` still counts it, so the Dividends
    # tab and Σ Holdings income would disagree with nothing saying why — hence the warning, and
    # the ledger audit's invariant that the two totals tie. Zero-instance on the live book.
    dropped = []
    for d in divs:
        k = (bucket_by_acct_id.get(d["account_id"]), d["security_id"])
        if k not in pos:
            dropped.append(d["security_id"])
            continue
        amt = float(d["gross"] or 0)
        sec_ccy = (meta.get(k) or {}).get("currency") or "SGD"
        # absent currency means the payment was in the security's currency: the rows
        # the fold was written against never carried one, and treating the absence as
        # SGD would convert a USD dividend at 1:1.
        div_ccy = d.get("currency") or sec_ccy
        if div_ccy != sec_ccy:
            # income and XIRR flows are in the security's currency, same as -qty*price.
            # Leaving the gross unconverted counts a euro as a dollar.
            amt = convert(amt, div_ccy, sec_ccy, fx)
        pos[k]["income"] += amt
        pos[k]["flows"].append((d["pay_date"] or today, amt))
    if dropped:
        log.warning("%d dividend row(s) on security_id(s) %s match no (bucket, security) "
                    "position and are left out of Holdings income", len(dropped),
                    sorted(set(dropped), key=str))

    _carry_corporate_actions(corp_actions, pos, meta)

    # a series named for its dates should arrive in them: the carry splices a predecessor's
    # events in at their original dates, mid-series. Stable, so same-day order is arrival order.
    for p in pos.values():
        p["unit_events"].sort(key=lambda e: e.date)
        p["cost_events"].sort(key=lambda e: e.date)
        p["entries"].sort(key=lambda e: e.date)
    return pos, meta


def fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today=None,
                   annotations=None, contracts=None):
    """Pure fold: accumulate per-(funding_bucket, security) positions from already-fetched
    inputs and emit one output row each. No DB or session — every input is plain data, so the
    cost-basis rules (transfer double-count, CDP cost attach, dividend income, corporate-action
    carry, switch rebasing, options income) are all testable with fabricated rows.

      txns  — mapping rows: account_id, account, funding_bucket, security_id, canonical_ticker,
              name, market, asset_type, currency, trade_date, action, qty_signed, price, fees.
      divs  — mapping rows: account_id, security_id, pay_date, gross, and currency
              when the payment is not in the security's currency.
      cdp   — {ticker: {flows, invested, buy_cost, buy_qty, cost_events, unit_lots}} from
              cdp_cost().
      corp_actions — iterable of (from_ticker, to_ticker, type), every `corporate_action` row;
              the fold moves cost along CARRY_TYPES and counts a split over all of them.
      options — {ticker: {pl_sgd, ...}} realized options income per underlying.
      fx / price — latest FX map and latest close per security_id. today defaults to today in
              SGT (`ingestion.prices.sg_today`), the date every price/FX row is stamped with.
      annotations — {natural key: condition} from portfolio.cost_annotations; the curated list
              when omitted. The free/transferred distinction is not in the ledger and cannot be
              put there, so it arrives as data like the corporate actions do.
      contracts — {ticker: [contract dicts]} from options.contracts_by_ticker(). The realized
              rollup in `options` cannot serve peak capital-at-risk: a denominator needs the
              strike, the size and the two dates of every contract, resolved or not.
    """
    today = today or sg_today()
    annotations = annotation_map() if annotations is None else annotations
    contracts = contracts or {}
    # rate_to_sgd fails loud on a currency `fx` has no rate for (BR4: never a silent 1.0), and
    # overview/positions/performance all share this one fold — so every txn, dividend and put
    # in such a currency is left out here, once, before any step converts it, until
    # ingestion.prices picks up a rate for it.
    unrated = ({r["currency"] for r in txns} | {d.get("currency") for d in divs}
               | {c.get("currency") for cs in contracts.values() for c in cs}) \
        - {None, "SGD"} - fx.keys()
    if unrated:
        log.warning("no FX rate for %s — leaving those positions out of totals", sorted(unrated))
        txns = [r for r in txns if r["currency"] not in unrated]
        divs = [d for d in divs if d.get("currency") not in unrated]
        contracts = {tk: [c for c in cs if c.get("currency") not in unrated]
                     for tk, cs in contracts.items()}
    pos, meta = _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations, fx)
    legs = legs_by_ticker(pos, meta)
    parts = {k: cost_partition(p) for k, p in pos.items() if k in meta}
    # the Net's verdict is a whole-ticker reading of SUMMED counts (#143 §8), and a leg's own
    # row depends on it (whether an all-unknown leg still carries its stock P/L), so it is
    # decided before any row is built.
    by_ticker = defaultdict(list)
    for k, part in parts.items():
        by_ticker[meta[k]["canonical_ticker"]].append(part)
    carries = {k: {**p["carry"], "ticker": meta[k]["canonical_ticker"]}
               for k, p in pos.items() if p["carry"] and k in meta}
    # last-wins over the same ordering `provenance` is built with below, so the verdict and the
    # `bound` the page renders beside it can never come from different carries of one ticker.
    bounds = {c["ticker"]: carry_bound(c)
              for _, c in sorted(carries.items(), key=lambda kc: str(kc[0]))}
    verdicts = {tk: net_verdict(ps, bounds.get(tk)) for tk, ps in by_ticker.items()}
    out = []
    pooled = defaultdict(list)
    for k, p in pos.items():
        m = meta.get(k)
        if not m:
            continue
        r = _build_row(k, p, m, fx, price, today, parts[k], verdicts[m["canonical_ticker"]])
        out.append(r)
        # the legs Holdings lists, so the pool is the name a consolidated row stands for; noise
        # rows `is_leg` drops carry no money to pool.
        if is_leg(r):
            pooled[r["ticker"]].append(_xirr_flows(p, price.get(k[1]), today, parts[k]))
    # whole-ticker like the verdict, and rides every leg (#110's "second fold keyed on the
    # security alone"): what Holdings' ticker mode shows for a name held in several buckets.
    ticker_xirr = {tk: rounded(_ticker_xirr(legs), 4) for tk, legs in pooled.items()}
    for r in out:
        r["ticker_xirr"] = ticker_xirr.get(r["ticker"])
    # a held security with no `price` row folds at a market value of ZERO — `mv_sgd: 0`, the
    # whole cost basis as unrealised loss and a breakeven solved against nothing — while
    # `alloc_by_account` skips the same row. `price: null` is the only other sign of it, so say
    # so: a new ticker before `make prices`, or a name Yahoo never priced.
    for tk in sorted({r["ticker"] for r in out if r["units"] > 1e-6 and not r["price"]}):
        log.warning("held security %s has no price row — its market value folds to 0", tk)
    # fold in the options income stream per underlying (realized, SGD). Options trade on the
    # cash account, so attach to the cash-bucket row for that security; orphan underlyings
    # (no stock position) are still counted in the Performance rollup via options.realized_by().
    # provenance is whole-ticker like the verdict it explains, and rides every leg. It is built
    # after the rows because naming a sibling needs to know whether Holdings lists it.
    listed = {(r["bucket"], r["ticker"]) for r in out if is_leg(r)}
    provenance = {c["ticker"]: _provenance(k, c, carries, listed, fx)
                  for k, c in sorted(carries.items(), key=lambda kc: str(kc[0]))}
    for r in out:
        r["provenance"] = provenance.get(r["ticker"])
        o = options.get(r["ticker"]) if r["bucket"] == "cash" else None
        # #143 §6: null omits the row instead of carrying a permanent `Options 0` line — 61 of the
        # live book's 73 legs. It reaches one state short of §6's NEVER EXISTED, though:
        # `realized_by_ticker()` keys on `_closed_trades()`, so an optioned name whose every leg is
        # still open has no key and lands here too. A name with one resolved leg ships its number
        # even when that number is zero. "measured zero" and "no stream" are different facts and
        # render differently, so readers must not take null for never-optioned — see BACKEND.md,
        # "The four cell states".
        r["options_pl_sgd"] = o["pl_sgd"] if o else None
        # Net and its verdict land here and not in `_build_row`, because the options stream is
        # one of Net's components and is attached only just above (#143 §15). The verdict is
        # whole-ticker and rides every leg; the Net is per leg, so a bucket column adds up on
        # its own and the columns add up to the name.
        r["net_verdict"] = verdicts[r["ticker"]]
        r["net_pl_sgd"] = _net_pl(r)
        # solved from the Net one line above it, and therefore never from quantities beside it.
        r["breakeven_price"] = _breakeven_price(r, r["units"],
                                                rate_to_sgd(r["currency"], fx))
    # peak capital-at-risk and the one percentage (#143 §9). Whole-ticker: the peak is a max
    # over the SUM of a name's legs, which is not the sum of their maxima, and the percentage
    # answers "did I make money on this name" rather than on one funding pool of it. The four
    # fields therefore repeat identically on every leg of a ticker — the same way `ticker`,
    # `name` and `currency` already do — so a consumer holding any one leg has the whole-ticker
    # answer without re-deriving it. They are read off a leg and lifted into the summary; the
    # per-bucket columns never carry them.
    rows = defaultdict(list)
    for r in out:
        rows[r["ticker"]].append(r)
    for tk, rs in rows.items():
        # `legs[tk]`, not `.get` — every output row came from an accumulator, so a miss is a
        # broken fold and should raise rather than quietly answer `no_capital`.
        figures = _return_figures(ticker_car(legs[tk], contracts.get(tk, ()), fx, today), rs)
        for r in rs:
            r.update(figures)
    return out
