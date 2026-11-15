"""One router per product, matching web/src/modules/{portfolio,networth,spending}/.

  portfolio  /api/overview, positions, performance, holding, dividend*, transactions, return,
             options, accounts. Also `_cache` (memoised fold; main's refresh clears it) and
             `ticker_ledger`
  networth   /api/networth/*: items, snapshots CRUD, latest, composition
  spending   /api/spending/*: summary, trends, transactions, recurring, classify/*

Handlers call the domain package and shape JSON; no arithmetic lives here. A test that
monkeypatches a handler's dependency patches it on the routes module that imported it.
"""
