"""DB loaders and market data. build/ turns statements into flat CSVs; this package puts them,
and live prices, into Postgres. Every loader is idempotent (dedup hash / duplicate-date skip)
and runs as `PYTHONPATH=. python -m ingestion.<module>`; `make ingest-all` runs them all.

  load                    build/ledger.csv + dividends.csv -> txn / dividend; its main() also
                          runs parse_options and load_cdp_cost. Home of the loader helpers
                          (`occ_hash`, `pdate`, `num` — None for blank, unlike build's 0.0)
  load_cash               build/cash_ledger.csv -> cash_txn, then classify.apply_rules
  load_cdp_cost           data/cdp-stocks/transactions.csv -> cdp_cost_lot
  parse_options           Tiger flex + IBKR option rows -> option_trade (parser and loader)
  prices                  Yahoo prices + FX and the Endowus NAV; owns `sg_today()`, the one
                          "today" (SGT) the whole repo uses
  dividend_announcements  SGX-declared dividends -> dividend_announcement(_component)
"""
