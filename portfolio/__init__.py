"""The domain package: one shared kernel plus the three products. It stays ONE package (read
docs/runbooks/BACKEND.md before proposing a split); the HTTP routes and the web modules are
what is split per product.

Kernel (everything else imports from here, never the other way)
  config            Settings (pydantic-settings, .env) and the `settings` singleton
  db                sessions (`session_scope`), latest price / FX reads, `fetch_dicts`
  models            the ORM: exactly what migrations/ creates (CI runs `alembic check`)
  money             the one native->SGD policy: `rate_to_sgd`, `to_sgd`, `convert`
  nullable          None-safe field helpers: `num`, `rounded`, `cents`, `iso`, `nulls_last`
  xirr              the one XIRR solver both return engines use
  flows             `flow_kind(action)`: external / return-in-kind / cost-in-kind
  cost_annotations  curated per-transaction free/transferred annotations
  sgx               SGX corporate-actions client and `CPF_SRS_SGX_NAMES`

Portfolio
  performance/      cost-basis fold per position -> Net, verdict, peak CAR, XIRR (package map
                    in its __init__)
  twr               time-weighted return + portfolio XIRR from daily prices (ADR 0001: a
                    separate engine from performance/, on purpose)
  dividends/        entitlement attribution, projection, Normal/Special split, yields
  options           the sold-option book: realised P/L, premium, by ticker/year

Net worth
  networth          snapshots, the three metrics, composition bands

Spending
  spending          ledger reads (summary, trends, transactions); `_where` and the
                    Postgres-only / portable SQL split
  classify          classification rules, NL -> rule compile, apply
  recurring         recurring-spend detection and the dismiss list
  spend_categories  the seed list of (category, subcategory)
"""
