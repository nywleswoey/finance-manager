"""Statement parsers: PDF / CSV statements in data/ -> normalised flat CSVs in build/.

No database here: everything under build/ reads data/ and writes build/*.csv (gitignored);
ingestion/ is what loads those into Postgres. Run as `PYTHONPATH=. python -m build.<name>`
(`make flat`, `make flat-cash`); import as `build.<name>` from tests and ingestion/.

  _ledgercommon    the shared parse-layer primitives: ticker canon/normalisation, name -> ticker
                   via the root symbols.csv, `num` (0.0 for a blank cell), FSM helpers,
                   MARKET_CCY, TIGER_FEE_COLS
  _pdf             `raw_text(path)`: pdftotext -layout, the one PDF reader
  _dates           `try_date(s, formats)`
  _csvout          `write_csv` / `write_rows`
  tiger_flex       the one reader for Tiger flex Activity Statements (sections, header maps)
  parse_moomoo     Moomoo PDFs            -> moomoo_events.csv
  parse_cdp        CDP PDFs (month diff)  -> cdp_events.csv
  parse_endowus    Endowus PDFs           -> endowus_events.csv (with cost)
  build_ledger     simple CSVs + Tiger flex + FSM + the three event files -> ledger.csv
  parse_dividends  Tiger / FSM / CDP / Moomoo / CPF-SRS dividends -> dividends.csv
  parse_options    Tiger flex option legs (the parser half; ingestion/load_options loads them)
  parse_cash       DBS / Trust / HSBC / DBS-CC statements -> cash_ledger_raw.csv
  classify_cash    adds is_spend / exclude_reason -> cash_ledger.csv
  fetch_cpf_srs_dividends  one-time network backfill -> data/cpf-srs-dividends.csv
"""
