"""Vercel serverless entrypoint. Vercel's @vercel/python runtime serves the ASGI
`app` exported here; framework detection finds this file, and every request —
/api/* and the static SPA alike — goes through this function. `vercel.json` at
the repo root layers on top of this (currently just the prices cron)."""
import os
import sys

# ensure the repo root is importable so `server.*` and `portfolio.*` resolve in the lambda
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.main import app  # noqa: E402,F401  (re-exported for the Vercel runtime)
