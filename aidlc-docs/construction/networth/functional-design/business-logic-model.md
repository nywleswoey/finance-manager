# Business Logic Model — networth

Lives in new `portfolio/networth.py`. Technology-agnostic logic below.

## Live portfolio value
Reuse existing performance compute: `portfolio_value_sgd = Σ row.mv_sgd` for open positions — same number `/api/overview` returns as `market_value_sgd`. Call it once at snapshot creation and freeze.

## FX conversion
`value_sgd = native_value × rate_to_sgd`, where:
- SGD → `rate_to_sgd = 1`
- else → latest `fx_rate.rate_to_sgd` for that currency with `date ≤ snapshot.date`
- if no rate exists for a non-SGD currency → **error** (do not assume 1). Surface which currency/date failed.

## Create snapshot (POST)
Input: `{ date, note?, values: [{ code|item_id, native_value, currency }] }`
1. Validate date not already used (unique). Validate every active catalogue item present (or default missing to 0 — see business-rules).
2. Compute live `portfolio_value_sgd`, store on snapshot.
3. For each value: resolve `rate_to_sgd` (freeze), compute `value_sgd` (freeze), insert `nw_value`.
4. Return the computed metrics (below).

## Metrics computation (per snapshot)
Given snapshot's `nw_value` rows (joined to `nw_item`) and frozen `P = portfolio_value_sgd`:

```
A_assets   = Σ value_sgd where item.kind = 'asset'
L_liab     = Σ value_sgd where item.kind = 'liability'
liquid     = Σ value_sgd where item.is_liquid
hou_assets = Σ value_sgd where item.is_housing and kind='asset'      # HDB
hou_liab   = Σ value_sgd where item.is_housing and kind='liability'  # home_loan + accrued
cpf_assets = Σ value_sgd where item.is_cpf and kind='asset'          # OA+SA+MA

total_assets             = A_assets + P
total_liabilities        = L_liab
net_worth                = total_assets - total_liabilities
net_worth_excl_housing   = net_worth - hou_assets + hou_liab
net_worth_excl_hou_cpf   = net_worth_excl_housing - cpf_assets
```

Returned metrics object (all SGD, rounded 2):
`{ date, total_assets, total_liabilities, liquid_assets, net_worth, net_worth_excl_housing, net_worth_excl_housing_cpf, portfolio_value_sgd }`

## Read operations
- **catalogue**: list active `nw_item` ordered by sort_order.
- **list snapshots**: each with date + computed `net_worth` (for history/trend).
- **get snapshot**: header + line values (item label, native, ccy, sgd) + full metrics.
- **latest**: most recent snapshot by date; used to prefill the create form.

## Data flow
```
create form (web) ──POST──> networth.create_snapshot
                                  ├─ compute live portfolio value (performance.compute)
                                  ├─ freeze fx per line (fx_rate)
                                  └─ persist snapshot + values
summary panel  <──GET──  networth.metrics(snapshot)
history chart  <──GET──  networth.list_snapshots → [{date, net_worth}]
```
