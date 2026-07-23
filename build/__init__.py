"""Statement parsers (PDF/CSV -> normalized flat files).

Marks build/ as a package so the ingestion loaders (run as `-m ingestion.*`
with the repo root on sys.path) can share the parse-layer primitives in
`build._ledgercommon` instead of re-copying them. The parser scripts themselves
still run as bare scripts (`python3 build/x.py`, build/ on sys.path[0]) and
import their siblings by bare name; this file is inert in that mode.
"""
