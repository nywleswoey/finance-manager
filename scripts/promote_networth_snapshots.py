"""Promote net-worth snapshots from one store to another, frozen money intact.

Two databases hold different halves of the net-worth history (#86): the deployed Neon store holds
2026-07-10 / 07-25 / 08-05, local dev holds **two earlier** snapshots, 2026-06-21 and 06-30, on
its own id sequence. `portfolio/config.py` sets `env_file=".env"` and `.env` carries no
`DATABASE_URL`, so local Python always hits localhost while the deployed app always hits Neon —
neither environment has ever shown the whole series. This copies the missing snapshots across so
one store holds all five.

**Copy, never recompute.** `networth.create_snapshot` cannot do this job: it stamps *today's*
`live_portfolio_sgd()` and derives `value_sgd` from native x rate at the target's FX. Both are
frozen money captured at the snapshot date, and the target store has neither the prices nor the
rates that produced them — recomputing would rewrite history to the value of the day it ran. So
every one of `native_value`, `currency`, `rate_to_sgd`, `value_sgd`, `portfolio_value_sgd`,
`note` and `created_at` is carried over verbatim.

Items are matched by **code**, never by id: the two stores keep their own `nw_item` id sequences,
and a copied `item_id` would land a value on the wrong band or on nothing at all. The catalogues
must agree on every field the banding reads before anything is written.

**FX rows travel with the snapshots.** A promoted snapshot's frozen rate was read from an
`fx_rate` row dated on or before its own date; the target has no such row (deployed `fx_rate`
starts 2026-06-27). Without it the no-carry-back check cannot reproduce in the target, and
`update_snapshot` on the promoted snapshot would raise BR4 rather than edit — the snapshot would
arrive un-editable. Only the rows the promoted snapshots actually read are copied, and an
existing target row is never overwritten.

**The write is guarded.** The pre-existing series is fingerprinted — ids included — before the
write and re-read after the flush; any drift rolls the whole promotion back rather than
committing it and reporting the damage afterwards. "No existing snapshot is modified, renumbered
or deleted" is the one criterion `frozen_money_diff` structurally cannot cover, since that only
compares dates *both* stores hold and the target's own snapshots are in neither intersection.

Two integrity checks gate every promotion, the two the map ran on the June pair (#86):
  - **no BR2 omission** — every active catalogue item has a value row on the snapshot. A missing
    item is silently defaulted to 0 by `create_snapshot`, which is not a smaller net worth but a
    wrong one.
  - **no FX carry-back** — every non-SGD currency the snapshot values has an `fx_rate` row dated
    on or before the snapshot date, so nothing was valued at a later month's rate.

Usage (SOURCE is read-only; TARGET is the store being written):
  PYTHONPATH=. .venv/bin/python scripts/promote_networth_snapshots.py \
      --source postgresql+psycopg://... --target postgresql+psycopg://...            # dry-run
  ... --commit                                                                        # write
  ... --verify                          # both checks over the target's whole series, plus a
                                        # readback of every shared snapshot against the source

`--expect-count` / `--expect-span` assert the shape of the series rather than only its soundness.
They take no defaults on purpose: the count and span belong to the ticket, not the tool. For #93,

  ... --verify --expect-count 5 --expect-span 2026-06-21..2026-08-05

Both URLs default to `$PROMOTE_SOURCE_URL` / `$PROMOTE_TARGET_URL`. `--verify` is the re-runnable
form of the acceptance criteria: the integrity checks answer "is each snapshot sound", the series
check answers "is this the series that was asked for", and the readback answers "did the frozen
money and the frozen portfolio value survive the copy unchanged" — a claim only a comparison
against the store it came from can make, and one that should not rest on a diff taken by hand
before the write.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from portfolio.db import connect_args
from portfolio.models import FxRate, NwItem, NwSnapshot, NwValue
from portfolio.networth import fx_row_for

# The catalogue fields promotion depends on. `label` is included because the composition chart
# reads it; `id` is deliberately excluded — the stores keep separate sequences, which is the
# whole reason values are matched by code.
ITEM_FIELDS = ("kind", "currency_default", "is_liquid", "is_housing", "is_cpf", "sort_order",
               "label", "active")


def _items(s: Session) -> dict[str, NwItem]:
    return {i.code: i for i in s.scalars(select(NwItem)).all()}


def _only_in(a: dict, b: dict) -> list:
    """Keys `a` holds and `b` does not, sorted."""
    return sorted(a.keys() - b.keys())


def _field_diffs(a: dict, b: dict, fields: tuple) -> list[tuple]:
    """(key, field, source_value, target_value) for every field that differs on a key both dicts
    hold. The comparison shape the catalogue check and both halves of the readback share — three
    different sentences to report, but one definition of what "differs" means."""
    return [(k, f, getattr(a[k], f), getattr(b[k], f))
            for k in sorted(a.keys() & b.keys()) for f in fields
            if getattr(a[k], f) != getattr(b[k], f)]


def catalogue_diff(src: Session, tgt: Session) -> list[str]:
    """Every way the two catalogues disagree, as human-readable lines. Empty means the snapshots
    band identically in both stores and merge without reconciliation."""
    a, b = _items(src), _items(tgt)
    return ([f"{c}: in source, not in target" for c in _only_in(a, b)]
            + [f"{c}: in target, not in source" for c in _only_in(b, a)]
            + [f"{c}: {f} source={x!r} target={y!r}"
               for c, f, x, y in _field_diffs(a, b, ITEM_FIELDS)])


def missing_item_values(s: Session, snap: NwSnapshot) -> list[str]:
    """Integrity check 1 — no BR2 omission: catalogue items with no value row on this snapshot.

    Not "no zero values": a zero is a legitimate reading (the deployed store's `tiger_sgd` and
    `ibkr_sgd` are genuinely empty accounts), and the data model cannot tell a real zero from a
    defaulted one. A *missing row* is the part that is unambiguous.

    Every catalogue item, not just the active ones. `create_snapshot` writes a row per *active*
    item, so scoping this check the same way would let an item deactivated between capture and
    promotion go missing without a word — and the acceptance criterion is "every catalogue
    item". Over-reporting here costs a line of output; under-reporting loses a band."""
    valued = {v.item.code for v in snap.values}
    return [f"{snap.date}: no value row for {c}"
            for c in sorted(c for c in _items(s) if c not in valued)]


def _currencies(snap: NwSnapshot) -> list[str]:
    """The non-SGD currencies this snapshot values. SGD is 1:1 by policy and never looked up."""
    return sorted({v.currency for v in snap.values if v.currency != "SGD"})


def fx_carry_backs(s: Session, snap: NwSnapshot) -> list[str]:
    """Integrity check 2 — no FX carry-back: currencies with no fx_rate row on or before the
    snapshot date. `ensure_fx` resolves that case by back-stamping the nearest *later* rate,
    which values a June snapshot at a later month's FX."""
    return [f"{snap.date}: no fx_rate for {c} on or before {snap.date}"
            for c in _currencies(snap) if fx_row_for(s, c, snap.date) is None]


def _fx_rows(s: Session, snap: NwSnapshot) -> list[dict]:
    """The fx_rate rows this snapshot's frozen rates were read from, so the check reproduces in
    the target. Carries the row as dated in the source, not the frozen rate off the value: the
    two can differ where a day's rate was refreshed after the snapshot froze it, and it is the
    row — the evidence that no carry-back was needed — that the target lacks."""
    rows = [fx_row_for(s, ccy, snap.date) for ccy in _currencies(snap)]
    return [{"date": r.date, "currency": r.currency, "rate_to_sgd": r.rate_to_sgd} for r in rows]


def plan(src: Session, tgt: Session) -> list[dict]:
    """What promotion would write: one row per source snapshot the target has no date for,
    oldest first. Writes nothing. Raises ValueError if the catalogues differ or any candidate
    fails an integrity check — both are conditions the promotion claims do not hold, so finding
    one means stopping rather than reconciling."""
    diff = catalogue_diff(src, tgt)
    if diff:
        raise ValueError("catalogue differs between the stores; refusing to promote:\n  "
                         + "\n  ".join(diff))
    have = {d for (d,) in tgt.execute(select(NwSnapshot.date))}
    rows = []
    for snap in src.scalars(select(NwSnapshot).order_by(NwSnapshot.date)):
        if snap.date in have:
            continue
        problems = missing_item_values(src, snap) + fx_carry_backs(src, snap)
        if problems:
            raise ValueError("integrity check failed; refusing to promote:\n  "
                             + "\n  ".join(problems))
        rows.append({
            "date": snap.date,
            "note": snap.note,
            "created_at": snap.created_at,
            "portfolio_value_sgd": snap.portfolio_value_sgd,
            "values": [{"code": v.item.code, "native_value": v.native_value,
                        "currency": v.currency, "rate_to_sgd": v.rate_to_sgd,
                        "value_sgd": v.value_sgd}
                       for v in sorted(snap.values, key=lambda v: v.item.sort_order)],
            "fx": _fx_rows(src, snap),
        })
    return rows


def series_fingerprint(s: Session) -> dict:
    """Every snapshot in a store reduced to a comparable tuple, keyed by date: its id, the frozen
    snapshot fields, and every value row. The `id` is in there deliberately — "renumbered" is one
    of the three things the promotion promises not to do, and it is the one a field-by-field money
    comparison would miss entirely."""
    return {sn.date: (sn.id, sn.note, sn.portfolio_value_sgd, sn.created_at,
                      tuple(sorted((v.item.code, v.native_value, v.currency, v.rate_to_sgd,
                                    v.value_sgd) for v in sn.values)))
            for sn in s.scalars(select(NwSnapshot))}


def fingerprint_drift(before: dict, after: dict) -> list[str]:
    """AC4 — no existing snapshot modified, renumbered or deleted. Dates present in `before` that
    changed or vanished. Dates only in `after` are the promotion doing its job, never drift.

    This is the criterion `frozen_money_diff` structurally cannot cover: that one compares dates
    *both* stores hold, so the target's own pre-existing snapshots — the very rows AC4 is about —
    sit in no comparison at all."""
    return ([f"{d}: snapshot no longer in the target" for d in _only_in(before, after)]
            + [f"{d}: existing snapshot changed\n      was {before[d]!r}\n      now {after[d]!r}"
               for d in sorted(before.keys() & after.keys()) if before[d] != after[d]])


def write_snapshots(tgt: Session, rows: list[dict]) -> None:
    """Write the planned snapshots. Insert-only: no existing snapshot, value, catalogue item or
    fx_rate row is touched, and the target's own id sequence assigns the new ids.

    "Insert-only" is enforced, not just intended: the pre-existing series is fingerprinted before
    the write and re-read after the flush, and any drift rolls the whole thing back rather than
    committing damage and reporting it afterwards. AC4 fails closed."""
    before = series_fingerprint(tgt)
    items = _items(tgt)
    for r in rows:
        for f in r["fx"]:
            if _exists_fx(tgt, f):
                continue
            tgt.add(FxRate(date=f["date"], currency=f["currency"],
                           rate_to_sgd=f["rate_to_sgd"]))
        snap = NwSnapshot(date=r["date"], note=r["note"],
                          portfolio_value_sgd=r["portfolio_value_sgd"])
        if r.get("created_at") is not None:
            # When it was captured, not when it was copied. Guarded rather than assigned blind:
            # the column is NOT NULL with only a server_default, so passing a source NULL
            # straight through would suppress that default and fail the insert instead of
            # falling back to it.
            snap.created_at = r["created_at"]
        tgt.add(snap)
        tgt.flush()
        for v in r["values"]:
            tgt.add(NwValue(snapshot_id=snap.id, item_id=items[v["code"]].id,
                            native_value=v["native_value"], currency=v["currency"],
                            rate_to_sgd=v["rate_to_sgd"], value_sgd=v["value_sgd"]))
    tgt.flush()
    drift = fingerprint_drift(before, series_fingerprint(tgt))
    if drift:
        tgt.rollback()
        raise RuntimeError("the write disturbed an existing snapshot; rolled back:\n  "
                           + "\n  ".join(drift))
    tgt.commit()


def _exists_fx(tgt: Session, f: dict) -> bool:
    return tgt.get(FxRate, {"date": f["date"], "currency": f["currency"]}) is not None


def verify(s: Session) -> list[str]:
    """Run both integrity checks over every snapshot in a store. Empty means the whole series
    is clean."""
    problems = []
    for snap in s.scalars(select(NwSnapshot).order_by(NwSnapshot.date)):
        problems += missing_item_values(s, snap) + fx_carry_backs(s, snap)
    return problems


def series_expectation(s: Session, count: int | None = None,
                       span: tuple | None = None) -> list[str]:
    """AC1 — the shape of the series the promotion was for: how many snapshots, spanning which
    dates. Both optional, because the count and span belong to the *ticket*, not to the tool —
    baking #93's five points and 2026-06-21..2026-08-05 in as defaults would make a general
    promotion script quietly wrong for the next one. Passing neither checks nothing.

    Worth asserting at all because `plan` promotes whatever dates the target happens to lack: a
    source missing a snapshot, or a target that already held a stray one, both merge cleanly and
    leave a series that is sound but not the one that was asked for."""
    dates = sorted(d for (d,) in s.execute(select(NwSnapshot.date)))
    out = []
    if count is not None and len(dates) != count:
        out.append(f"expected {count} snapshot(s), found {len(dates)}")
    if span is not None and dates and (dates[0], dates[-1]) != tuple(span):
        out.append(f"expected the series to span {span[0]}..{span[1]}, "
                   f"found {dates[0]}..{dates[-1]}")
    return out


# What must survive the copy untouched, per row. `native_value` and `currency` are here as much
# as the money is: a rate that round-trips against a rewritten native is still a rewritten value.
VALUE_FIELDS = ("native_value", "currency", "rate_to_sgd", "value_sgd")
# `created_at` is here because `apply` carries it deliberately — when the snapshot was captured,
# not when it was copied. Left out, a snapshot that arrived stamped with the copy time would read
# back clean and the promotion's "verbatim" claim would go unchecked.
SNAPSHOT_FIELDS = ("note", "portfolio_value_sgd", "created_at")


def frozen_money_diff(src: Session, tgt: Session) -> list[str]:
    """Every way a snapshot both stores hold disagrees between them — the readback that says the
    frozen money round-tripped rather than being recomputed, and that the frozen portfolio value
    is the one captured at the time.

    Separate from the integrity checks because it answers a different question. Those ask
    whether a snapshot is internally sound; this asks whether the copy was faithful, which only
    a comparison against the store it came from can answer. Re-runnable, so the claim does not
    rest on a diff someone took by hand before the write."""
    a = {sn.date: sn for sn in src.scalars(select(NwSnapshot))}
    b = {sn.date: sn for sn in tgt.scalars(select(NwSnapshot))}
    out = [f"{d}: {f} source={x!r} target={y!r}"
           for d, f, x, y in _field_diffs(a, b, SNAPSHOT_FIELDS)]
    for date in sorted(a.keys() & b.keys()):
        va = {v.item.code: v for v in a[date].values}
        vb = {v.item.code: v for v in b[date].values}
        out += [f"{date}: {c} valued in source, not in target" for c in _only_in(va, vb)]
        out += [f"{date}: {c} valued in target, not in source" for c in _only_in(vb, va)]
        out += [f"{date}: {c}.{f} source={x!r} target={y!r}"
                for c, f, x, y in _field_diffs(va, vb, VALUE_FIELDS)]
    return out


def _session(url: str) -> Session:
    return sessionmaker(bind=create_engine(url, future=True, connect_args=connect_args(url)),
                        future=True)()


def _host(url: str) -> str:
    return url.split("@")[-1].split("/")[0].split("?")[0] if "@" in url else url


def _report(s: Session, label: str) -> None:
    rows = [(snap.date, len(snap.values), float(snap.portfolio_value_sgd or 0))
            for snap in s.scalars(select(NwSnapshot).order_by(NwSnapshot.date))]
    print(f"{label}: {len(rows)} snapshot(s)")
    for d, n, p in rows:
        print(f"  {d}  {n:>2} values  portfolio {p:>16,.2f}")


def _print_problems(label: str, clean: str, problems: list[str]) -> int:
    """Print a check's verdict and return the exit code it implies."""
    print(f"\n{label}: " + (clean if not problems else f"{len(problems)} PROBLEM(S)"))
    for p in problems:
        print(f"  ! {p}")
    return 1 if problems else 0


INTEGRITY_CLEAN = "CLEAN — no BR2 omission, no FX carry-back"
READBACK_CLEAN = "CLEAN — frozen money and frozen portfolio value identical to the source"
SERIES_CLEAN = "CLEAN — the series is the count and span that were asked for"


def _readback(source_url: str, tgt: Session) -> int:
    """Read every shared snapshot back against the store it came from. Opens its own session so
    the caller never has to hold one open across the write."""
    src = _session(source_url)
    try:
        return _print_problems("readback vs source", READBACK_CLEAN, frozen_money_diff(src, tgt))
    finally:
        src.close()


def _span(text: str) -> tuple:
    """`--expect-span FIRST..LAST`, as two dates."""
    try:
        first, last = text.split("..")
        return dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected FIRST..LAST as ISO dates, got {text!r}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=os.environ.get("PROMOTE_SOURCE_URL"),
                    help="store to read snapshots from (never written)")
    ap.add_argument("--target", default=os.environ.get("PROMOTE_TARGET_URL"),
                    help="store to promote them into")
    ap.add_argument("--commit", action="store_true", help="write (otherwise dry-run)")
    ap.add_argument("--verify", action="store_true",
                    help="run both integrity checks over the target's whole series and stop; "
                         "with --source, also read every shared snapshot back against it")
    ap.add_argument("--expect-count", type=int, metavar="N",
                    help="assert the target holds exactly N snapshots (AC1)")
    ap.add_argument("--expect-span", type=_span, metavar="FIRST..LAST",
                    help="assert the target's series runs from FIRST to LAST (AC1)")
    args = ap.parse_args(argv)
    if not args.target:
        ap.error("--target (or PROMOTE_TARGET_URL) is required")
    expected = (args.expect_count, args.expect_span)

    tgt = _session(args.target)
    try:
        if args.verify:
            _report(tgt, f"target {_host(args.target)}")
            rc = _print_problems("integrity", INTEGRITY_CLEAN, verify(tgt))
            if any(e is not None for e in expected):
                rc |= _print_problems("series", SERIES_CLEAN,
                                      series_expectation(tgt, *expected))
            if args.source:
                rc |= _readback(args.source, tgt)
            return rc

        if not args.source:
            ap.error("--source (or PROMOTE_SOURCE_URL) is required unless --verify")
        src = _session(args.source)
        try:
            _report(src, f"source {_host(args.source)}")
            print()
            _report(tgt, f"target {_host(args.target)}")
            rows = plan(src, tgt)
        finally:
            src.close()

        if not rows:
            print("\nNothing to promote: the target already holds every source date.")
            return 0

        print(f"\ncatalogue: identical across both stores ({len(_items(tgt))} items)")
        for r in rows:
            print(f"\n=== {r['date']}  note={r['note']!r}")
            print(f"  portfolio_value_sgd {float(r['portfolio_value_sgd']):>16,.2f}  (frozen, copied)")
            print(f"  integrity: no BR2 omission ({len(r['values'])} items valued), no FX carry-back")
            for f in r["fx"]:
                print(f"  fx carried: {f['date']} {f['currency']} {f['rate_to_sgd']}")
            print(f"  {'code':<20}{'native':>16} {'ccy':<4}{'rate':>14}{'value_sgd':>16}")
            print("  " + "-" * 70)
            for v in r["values"]:
                print(f"  {v['code']:<20}{float(v['native_value']):>16,.2f} {v['currency']:<4}"
                      f"{float(v['rate_to_sgd']):>14.8f}{float(v['value_sgd']):>16,.2f}")

        if not args.commit:
            print("\nDRY-RUN. Re-run with --commit to write.")
            return 0

        write_snapshots(tgt, rows)
        print(f"\nCOMMITTED {len(rows)} snapshot(s). "
              "No pre-existing snapshot changed — the write is guarded and rolls back if one does.\n")
        _report(tgt, f"target {_host(args.target)}")
        rc = _print_problems("integrity over the merged series", INTEGRITY_CLEAN, verify(tgt))
        if any(e is not None for e in expected):
            rc |= _print_problems("series", SERIES_CLEAN, series_expectation(tgt, *expected))
        rc |= _readback(args.source, tgt)
        return rc
    finally:
        tgt.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
