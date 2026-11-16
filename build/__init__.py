"""Statement parsers (PDF/CSV -> normalized flat files).

Marks build/ as a package so the ingestion loaders (run as `-m ingestion.*`
with the repo root on sys.path) can share the parse-layer primitives in
`build._ledgercommon` instead of re-copying them. The parser scripts themselves
still run as bare scripts (`python build/x.py`, build/ on sys.path[0]) and
import their siblings by bare name; this file is inert in that mode.

Shared primitives (bare-name importable by the scripts, package-importable by ingestion)
  _ledgercommon  `ALIAS`/`canon`, the `num` money parser (0.0 for blank), `norm_ticker`,
                 `name_to_ticker` (symbols.csv), `market_of`, `MARKET_CCY`, `TIGER_FEE_COLS`
  _dates         `try_date(s, formats)`: first strptime format that parses, else None
  _csvout        `write_csv(path, fieldnames, rows)`
  _pdf           `raw_text(path)`: poppler `pdftotext -layout`

Portfolio statements -> flat files
  parse_cdp                  CDP monthly PDFs -> cdp_events.csv (snapshot-diffed share moves)
  parse_moomoo               Moomoo monthly PDFs -> moomoo_events.csv
  parse_endowus              Endowus statements -> endowus_events.csv (fund units with cost)
  build_ledger               every source under data/ -> ledger.csv, then replays it against
                             Holdings.md to surface discrepancies
  parse_dividends            cash dividends from every statement source -> dividends.csv
  export_dividends_master    dividends.csv -> data/dividends-master.csv (per-unit rate reference)
  fetch_cpf_srs_dividends    one-time CPF/SRS dividend backfill -> data/cpf-srs-dividends.csv
                             (reads `portfolio.sgx.CPF_SRS_SGX_NAMES`)

Spending statements -> flat files
  parse_cash                 bank + card PDFs -> cash_ledger_raw.csv
  classify_cash              cash_ledger_raw.csv -> cash_ledger.csv (is_spend / exclude_reason;
                             category is DB-owned, see portfolio.classify)
"""
