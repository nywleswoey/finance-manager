# Frontend Components — networth

Stack: React 18 + Vite, recharts available. New module `web/src/modules/networth/NetWorth.jsx`, wired as a tab in `App.jsx` ("Net Worth"). API calls via existing `web/src/api.js` helper.

## Component hierarchy
```
<NetWorth>                         top-level tab page; fetches catalogue + snapshots on mount
 ├─ <SummaryCards metrics>         6 metric cards from latest snapshot
 ├─ <NetWorthTrend snapshots>      recharts line: net_worth over date
 ├─ <SnapshotForm catalogue prefill onSave>   create new dated snapshot
 └─ <HistoryTable snapshots onSelect onDelete>  list past snapshots
```

## SummaryCards
- Props: `metrics` (the 6 figures + portfolio_value_sgd).
- Cards: Total Assets, Total Liabilities, Liquid Assets, Net Worth, Net Worth excl. Housing, Net Worth excl. Housing & CPF. SGD, thousands-formatted.

## SnapshotForm
- Props: `catalogue` (14 items), `prefill` (latest snapshot's line values), `onSave`.
- State: `date` (default today), `note`, `rows` keyed by item code → `{ native_value, currency }`.
- Rendering: group by section — **Cash/Liquid**, **SRS**, **CPF**, **Housing (assets)**, **Liabilities**. Each row: label, value input, currency (prefilled from item.currency_default or prefill; SGD locked for SGD items, editable for HKD/USD).
- Live portfolio value shown read-only ("pulled live at save").
- Validation: numeric inputs; date required & not duplicate (server enforces, surface 409).
- On submit → POST `/api/networth/snapshots`; on success refresh summary + history.

## NetWorthTrend
- recharts `<LineChart>` of `{date, net_worth}` from snapshot list. Optional extra lines: net_worth_excl_housing.

## HistoryTable
- Columns: date, total assets, total liab, net worth, excl-housing, excl-housing-cpf.
- Row click → load that snapshot's detail into SummaryCards. Delete button → DELETE snapshot (allows re-entry for a date).

## API integration points
| Component | Endpoint |
|-----------|----------|
| NetWorth (mount) | GET /api/networth/items, GET /api/networth/snapshots, GET /api/networth/latest |
| SnapshotForm save | POST /api/networth/snapshots |
| HistoryTable select | GET /api/networth/snapshots/{id} |
| HistoryTable delete | DELETE /api/networth/snapshots/{id} |
