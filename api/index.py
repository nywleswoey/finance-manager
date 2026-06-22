"""Vercel serverless entrypoint. Vercel's @vercel/python runtime serves the ASGI
`app` exported here; vercel.json routes all /api/* requests to this function."""
import os
import sys

# ensure the repo root is importable so `api.*` and `portfolio.*` resolve in the lambda
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.main import app  # noqa: E402,F401  (re-exported for the Vercel runtime)
