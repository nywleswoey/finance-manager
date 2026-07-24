"""SQLAlchemy 2.0 models — mirrors the schema in PLAN.md.

Money/qty use Numeric for exactness. Enum-like fields are String (broker formats vary);
constrained in app code, not DB enums, to stay flexible as new statement types appear.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres (indexable, native), plain JSON on SQLite so the model builds under the
# in-memory test DB (tests/test_spending.py et al.).
JSON_B = JSON().with_variant(JSONB, "postgresql")

QTY = Numeric(20, 8)
MONEY = Numeric(20, 4)
RATE = Numeric(20, 8)


class Base(DeclarativeBase):
    pass


# ---------------- reference ----------------
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)        # Tiger Prime, CDP, CPF, SRS, Moomoo, FSM
    broker: Mapped[str | None] = mapped_column(String(64))
    funding_bucket: Mapped[str] = mapped_column(String(8))           # cash | cpf | srs
    base_currency: Mapped[str] = mapped_column(String(3), default="SGD")
    opened: Mapped[dt.date | None] = mapped_column(Date)
    closed: Mapped[dt.date | None] = mapped_column(Date)
    __table_args__ = (CheckConstraint("funding_bucket in ('cash','cpf','srs')"),)


class Security(Base):
    __tablename__ = "security"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_ticker: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    market: Mapped[str | None] = mapped_column(String(4))            # US | HK | SG
    asset_type: Mapped[str] = mapped_column(String(16), default="stock")  # stock|fund|reit|etf|bond
    currency: Mapped[str | None] = mapped_column(String(3))
    isin: Mapped[str | None] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    aliases: Mapped[list[SecurityAlias]] = relationship(back_populates="security", cascade="all, delete-orphan")


class SecurityAlias(Base):
    __tablename__ = "security_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(128))                  # code or name variant
    source: Mapped[str | None] = mapped_column(String(32))
    security: Mapped[Security] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("alias", name="uq_alias"),)


class CorporateAction(Base):
    __tablename__ = "corporate_action"
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("security.id"))
    date: Mapped[dt.date | None] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(16))                    # rename|split|consolidation|merger|distribution
    from_ticker: Mapped[str | None] = mapped_column(String(24))
    to_ticker: Mapped[str | None] = mapped_column(String(24))
    ratio_num: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ratio_den: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------- ledger ----------------
class ImportBatch(Base):
    __tablename__ = "import_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(256))
    file_hash: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rows_in: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    __table_args__ = (UniqueConstraint("file_hash", name="uq_batch_filehash"),)


class Txn(Base):
    __tablename__ = "txn"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    security_id: Mapped[int | None] = mapped_column(ForeignKey("security.id"))
    trade_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    settle_date: Mapped[dt.date | None] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(24))                  # buy|sell|gift_in|rights|bonus|scrip|corp_action|transfer_in|transfer_out|fee|subscription
    qty_signed: Mapped[Decimal] = mapped_column(QTY, default=0)
    price: Mapped[Decimal | None] = mapped_column(MONEY)
    gross_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    fees: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    funding_bucket: Mapped[str | None] = mapped_column(String(8))
    source_file: Mapped[str | None] = mapped_column(String(256))
    raw: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    dedup_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_txn_dedup"),)


class Dividend(Base):
    __tablename__ = "dividend"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    security_id: Mapped[int | None] = mapped_column(ForeignKey("security.id"))
    ex_date: Mapped[dt.date | None] = mapped_column(Date)
    pay_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(8), default="cash")     # cash | scrip
    amount_per_unit: Mapped[Decimal | None] = mapped_column(RATE)
    units: Mapped[Decimal | None] = mapped_column(QTY)
    gross: Mapped[Decimal | None] = mapped_column(MONEY)
    withholding_tax: Mapped[Decimal | None] = mapped_column(MONEY)
    net: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    source_file: Mapped[str | None] = mapped_column(String(256))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    dedup_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_div_dedup"),)


# ---------------- spending (cash-flow ledger) ----------------
class CashTxn(Base):
    """One bank/credit-card cash-flow line — the spending ledger (distinct from the
    securities `txn`). Outflows are spend candidates; `is_spend` is the filtered truth
    after exclusions (credit-card bill payments, brokerage/internal transfers, income).

    amount_sgd is SIGNED: negative = outflow (money leaving), positive = inflow.
    Double-counting is avoided by excluding DBS->credit-card bill payments — the card's
    own line items (HSBC/Trust statements) are the source of truth for that spend.
    """
    __tablename__ = "cash_txn"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(8))                    # dbs | hsbc | trust
    account_label: Mapped[str] = mapped_column(String(32))            # DBS | HSBC Live+ | Trust
    txn_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    post_date: Mapped[dt.date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)             # cleaned, multi-line joined
    merchant: Mapped[str | None] = mapped_column(String(128))        # key used for categorization
    amount_sgd: Mapped[Decimal | None] = mapped_column(MONEY)        # signed: -outflow / +inflow
    fcy_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    fcy_currency: Mapped[str | None] = mapped_column(String(3))
    direction: Mapped[str] = mapped_column(String(6))                # debit | credit
    is_spend: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[str | None] = mapped_column(String(24))   # cc_payment|brokerage_transfer|internal_transfer|income|refund|investment
    category: Mapped[str | None] = mapped_column(String(48))         # denormalized; owned by classification
    subcategory: Mapped[str | None] = mapped_column(String(48))
    # provenance (rule-based spend classification). unclassified = category IS NULL AND
    # classification_source IS NULL. classified_by_rule_id set iff source = 'rule'.
    classification_source: Mapped[str | None] = mapped_column(String(6))  # NULL | rule | manual
    classified_by_rule_id: Mapped[int | None] = mapped_column(ForeignKey("classification_rule.id"))
    classified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source_file: Mapped[str | None] = mapped_column(String(256))
    raw: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    dedup_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_cash_dedup"),)


# ---------------- spend classification (rule-based) ----------------
class SpendCategory(Base):
    """The fixed personal taxonomy of (category, subcategory) pairs — the single source of
    truth that drives the classify dropdown and validates rules + manual classifications.
    Seeded from portfolio.spend_categories. `cash_txn` keeps denormalized string columns
    (not FK'd here) so existing spend queries stay untouched."""
    __tablename__ = "spend_category"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(48))
    subcategory: Mapped[str] = mapped_column(String(48))
    __table_args__ = (UniqueConstraint("category", "subcategory", name="uq_spend_category"),)


class ClassificationRule(Base):
    """A persistent spend-classification rule. Authored in natural language (`nl_text`),
    compiled once to deterministic ANDed predicates (`predicates` JSONB) targeting one
    `spend_category`. Highest `priority` wins a multi-match; `active` gates whether it fires
    on future imports. Applied by portfolio.classify.apply_rules."""
    __tablename__ = "classification_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    nl_text: Mapped[str] = mapped_column(Text)                        # human identity + provenance
    predicates: Mapped[dict] = mapped_column(JSON_B)                  # {"conditions": [...]}, ANDed
    category_id: Mapped[int] = mapped_column(ForeignKey("spend_category.id"))  # target pair
    priority: Mapped[int] = mapped_column(Integer, default=0)         # explicit order; highest wins
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RecurringSpend(Base):
    """A user-defined recurring charge (subscription, rent, insurance, loan...). Matched
    against the cash_txn ledger by `merchant_match` (case-insensitive substring) to surface
    actual occurrences + timing (last seen, typical day-of-month, next due). Definitions are
    entered in-app; auto-detection suggests candidates but does NOT write rows here.
    """
    __tablename__ = "recurring_spend"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))                    # user label: "Netflix", "Rent"
    merchant_match: Mapped[str | None] = mapped_column(String(128))  # substring matched vs cash_txn.merchant
    category: Mapped[str | None] = mapped_column(String(48))
    cadence: Mapped[str] = mapped_column(String(12), default="monthly")  # weekly|monthly|quarterly|annual
    expected_amount: Mapped[Decimal | None] = mapped_column(MONEY)   # SGD, positive magnitude
    expected_day: Mapped[int | None] = mapped_column(Integer)        # day-of-month it usually lands
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecurringDismissed(Base):
    """A detected-recurring merchant the user dismissed as a false positive. Auto-detection
    (portfolio.recurring.detect_candidates) skips any merchant listed here, so a rejected
    suggestion never resurfaces. Manual tracking is unaffected — a dismissed merchant can
    still be added by hand as a RecurringSpend.
    """
    __tablename__ = "recurring_dismissed"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant: Mapped[str] = mapped_column(String(128))               # exact detected merchant string
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("merchant", name="uq_recurring_dismissed_merchant"),)


# ---------------- options ----------------
class OptionTrade(Base):
    """One sold-option contract line (wheel strategy: cash-secured puts + covered calls).

    P&L is realized in the contract's native currency:
        realized = (premium_open - premium_close) * contracts * multiplier - fees_open - fees_close
    premium_open  = credit received per share when sold-to-open
    premium_close = debit paid per share to buy-to-close (0 when expired worthless / assigned)
    outcome       = expired | closed | assigned  (best-effort; assignment inferred elsewhere)
    """
    __tablename__ = "option_trade"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    security_id: Mapped[int | None] = mapped_column(ForeignKey("security.id"))  # underlying, if matched
    underlying: Mapped[str] = mapped_column(String(24))                  # raw ticker from source (BABA, PLTR)
    market: Mapped[str | None] = mapped_column(String(4))                # US | HK
    option_type: Mapped[str] = mapped_column(String(4))                  # put | call
    contracts: Mapped[Decimal] = mapped_column(QTY, default=0)
    strike: Mapped[Decimal | None] = mapped_column(MONEY)
    multiplier: Mapped[int] = mapped_column(Integer, default=100)
    open_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    expiry_date: Mapped[dt.date | None] = mapped_column(Date)
    close_date: Mapped[dt.date | None] = mapped_column(Date)
    premium_open: Mapped[Decimal | None] = mapped_column(MONEY)          # per share, credit
    premium_close: Mapped[Decimal | None] = mapped_column(MONEY)         # per share, debit to close
    fees_open: Mapped[Decimal | None] = mapped_column(MONEY)
    fees_close: Mapped[Decimal | None] = mapped_column(MONEY)
    realized_pl: Mapped[Decimal | None] = mapped_column(MONEY)           # native currency
    currency: Mapped[str | None] = mapped_column(String(3))
    outcome: Mapped[str | None] = mapped_column(String(12))              # expired | closed | assigned
    source_file: Mapped[str | None] = mapped_column(String(256))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    dedup_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_opt_dedup"),)


# ---------------- CDP cost log ----------------
class CdpCostLot(Base):
    """CDP purchase/sale price log. CDP monthly statements carry share MOVEMENTS but omit
    unit price, so the cost record lives here (was a runtime CSV: data/cdp-stocks/
    transactions.csv). Distinct from `txn`: this table supplies COST only — units come from
    the CDP `txn` rows — so the two are never double-counted (see performance.compute).

    amount is SIGNED: negative = cash out (buy), positive = proceeds (sell).
    """
    __tablename__ = "cdp_cost_lot"
    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(24))                     # raw CDP code
    ticker: Mapped[str] = mapped_column(String(24))                  # canonical (alias-resolved)
    stock_name: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str | None] = mapped_column(String(24))           # ipo | open market | sell | ...
    qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)            # signed: -buy / +sell
    currency: Mapped[str | None] = mapped_column(String(3))
    market: Mapped[str | None] = mapped_column(String(4))
    source_file: Mapped[str | None] = mapped_column(String(256))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    dedup_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_cdp_cost_dedup"),)


# ---------------- valuation ----------------
class Price(Base):
    __tablename__ = "price"
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str | None] = mapped_column(String(32))


class FxRate(Base):
    __tablename__ = "fx_rate"
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_to_sgd: Mapped[Decimal] = mapped_column(RATE)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id"))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    units: Mapped[Decimal] = mapped_column(QTY)
    market_value: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("account_id", "security_id", "date", "source", name="uq_snapshot"),)


# ---------------- net worth ----------------
class NwItem(Base):
    """Fixed catalogue of manual asset/liability line items. Tags drive the metrics.
    The live investment portfolio is NOT a row here — it enters via the snapshot's
    frozen portfolio_value_sgd."""
    __tablename__ = "nw_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)        # posb, tiger_hkd, cpf_oa, hdb, home_loan
    label: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(9))                      # asset | liability
    currency_default: Mapped[str] = mapped_column(String(3), default="SGD")
    is_liquid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_housing: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cpf: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("kind in ('asset','liability')", name="ck_nw_item_kind"),)


class NwSnapshot(Base):
    """One dated net-worth snapshot. Live portfolio value frozen at capture so history
    stays stable when prices move."""
    __tablename__ = "nw_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, unique=True, index=True)
    note: Mapped[str | None] = mapped_column(String(256))
    portfolio_value_sgd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    values: Mapped[list[NwValue]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class NwValue(Base):
    """Per-snapshot value of one catalogue item. fx + sgd value frozen at capture."""
    __tablename__ = "nw_value"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("nw_snapshot.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("nw_item.id"))
    native_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    rate_to_sgd: Mapped[Decimal] = mapped_column(RATE, default=1)
    value_sgd: Mapped[Decimal] = mapped_column(MONEY, default=0)

    snapshot: Mapped[NwSnapshot] = relationship(back_populates="values")
    item: Mapped[NwItem] = relationship()
    __table_args__ = (UniqueConstraint("snapshot_id", "item_id", name="uq_nw_value"),)
