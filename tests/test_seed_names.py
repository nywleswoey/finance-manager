"""scripts.seed.names_from_ledger() — a display name must come from the instrument, never
from whichever row happened to create the security.

AMZN's only ledger rows are gifted-stock-in transfers with no real instrument name in `raw`,
so the loader promoted the row's own action description ("Gifted Stock In") to the security's
name and SecurityDetail rendered "GIFTED STOCK IN" as AMZN's heading (#145).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_seed_names.py -q
"""
import csv

import scripts.seed as seed

FIELDS = ["date", "account", "market", "ticker", "asset_type", "action", "qty_signed",
          "price", "amount", "currency", "fees", "source", "raw"]


def _write_ledger(tmp_path, rows):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    with open(build_dir / "ledger.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**dict.fromkeys(FIELDS, ""), **r})
    return str(tmp_path)


def _row(**k):
    return dict(date="2024-01-01", account="Moomoo", market="US", asset_type="stock", **k)


def test_transfer_only_row_never_promotes_its_own_action_as_the_name(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "ROOT", _write_ledger(tmp_path, [
        _row(ticker="AMZN", action="gifted stock in", qty_signed="10", raw="Gifted Stock In"),
    ]))
    assert seed.names_from_ledger() == {}


def test_action_text_with_a_ticker_suffix_is_also_rejected(tmp_path, monkeypatch):
    """The Tiger transfer loader sometimes appends the code as '(CODE)'; that shape must not
    smuggle the action description past the exact-string guard."""
    monkeypatch.setattr(seed, "ROOT", _write_ledger(tmp_path, [
        _row(ticker="AMZN", action="gifted stock in", qty_signed="10",
             raw="Gifted Stock In (AMZN)"),
    ]))
    assert seed.names_from_ledger() == {}


def test_a_real_trade_row_still_yields_its_display_name(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "ROOT", _write_ledger(tmp_path, [
        _row(ticker="BABA", action="buy", qty_signed="5", raw="Alibaba Group Holding (BABA)"),
    ]))
    assert seed.names_from_ledger() == {"BABA": "Alibaba Group Holding"}


def test_a_real_name_alongside_a_later_gift_is_not_displaced(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "ROOT", _write_ledger(tmp_path, [
        _row(ticker="BABA", action="buy", qty_signed="5", raw="Alibaba Group Holding (BABA)"),
        _row(ticker="BABA", action="gifted stock in", qty_signed="1", raw="Gifted Stock In"),
    ]))
    assert seed.names_from_ledger() == {"BABA": "Alibaba Group Holding"}


def test_main_seeds_amzn_with_the_curated_name_not_the_gift_action(tmp_path, monkeypatch):
    root = _write_ledger(tmp_path, [
        _row(ticker="AMZN", action="gifted stock in", qty_signed="10", raw="Gifted Stock In"),
    ])
    monkeypatch.setattr(seed, "ROOT", root)
    monkeypatch.setattr(seed, "markets_from_options", lambda: {})
    monkeypatch.setattr(seed, "load_symbols", lambda: {})

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from portfolio.models import Base, Security

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    seed.main()

    with Session() as s:
        sec = s.scalar(select(Security).filter_by(canonical_ticker="AMZN"))
        assert sec.name == "Amazon.com, Inc."
        assert sec.name != "Gifted Stock In"
