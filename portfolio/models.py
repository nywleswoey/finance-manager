"""SQLAlchemy 2.0 models — mirrors the schema in PLAN.md.

Money/qty use Numeric for exactness. Enum-like fields are String (broker formats vary);
constrained in app code, not DB enums, to stay flexible as new statement types appear.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
