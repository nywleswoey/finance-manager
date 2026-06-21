# Domain Entities — networth

Three new tables. Money as `MONEY = Numeric(20,4)`, rates as `RATE = Numeric(20,8)` (match existing `models.py`).

## `nw_item` — fixed catalogue (seeded, 14 rows)
The line-item definitions. Tags drive every metric.

| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| code | str(32) unique | stable key, e.g. `posb`, `tiger_hkd`, `cpf_oa`, `hdb`, `home_loan`, `home_loan_accrued` |
| label | str(64) | display name |
| kind | str(9) | `asset` \| `liability` (CheckConstraint) |
| currency_default | str(3) | default native ccy for input prefill (SGD/HKD/USD) |
| is_liquid | bool | |
| is_housing | bool | |
| is_cpf | bool | |
| sort_order | int | UI ordering |
| active | bool | default true |

Seed (kind / ccy / liquid / housing / cpf):
| code | label | kind | ccy | liq | hou | cpf |
|------|-------|------|-----|:--:|:--:|:--:|
| posb | POSB Shared Account | asset | SGD | ✓ | | |
| dbs_multiplier | DBS Multiplier | asset | SGD | ✓ | | |
| srs | SRS Account | asset | SGD | | | |
| tiger_hkd | Tiger HKD Cash | asset | HKD | ✓ | | |
| tiger_sgd | Tiger SGD Cash | asset | SGD | ✓ | | |
| tiger_usd | Tiger USD Cash | asset | USD | ✓ | | |
| tiger_vault | Tiger Vault | asset | SGD | ✓ | | |
| ibkr_sgd | IBKR SGD Cash | asset | SGD | ✓ | | |
| cpf_oa | CPF OA | asset | SGD | | | ✓ |
| cpf_sa | CPF SA | asset | SGD | | | ✓ |
| cpf_ma | CPF MA | asset | SGD | | | ✓ |
| hdb | Tampines HDB | asset | SGD | | ✓ | |
| home_loan | CPF Home Loan | liability | SGD | | ✓ | |
| home_loan_accrued | CPF Home Loan Accrued Interest | liability | SGD | | ✓ | |

Note: live investment portfolio is **not** a catalogue row — it enters via the snapshot's frozen `portfolio_value_sgd`.

## `nw_snapshot` — dated snapshot header
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| date | Date unique | snapshot date (one per date) |
| note | str(256) null | optional |
| portfolio_value_sgd | MONEY | **frozen** live portfolio value at capture |
| created_at | DateTime tz | server_default now() |

## `nw_value` — per-snapshot line value
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| snapshot_id | FK nw_snapshot ON DELETE CASCADE | |
| item_id | FK nw_item | |
| native_value | MONEY | as entered |
| currency | str(3) | native ccy |
| rate_to_sgd | RATE | **frozen** fx used (1 for SGD) |
| value_sgd | MONEY | **frozen** = native_value × rate_to_sgd |
| UNIQUE(snapshot_id, item_id) | | |

Freezing `rate_to_sgd`, `value_sgd`, and `portfolio_value_sgd` makes historical snapshots immutable (NFR3).

## Relationships
- `nw_snapshot` 1—* `nw_value` (cascade delete)
- `nw_item` 1—* `nw_value`
