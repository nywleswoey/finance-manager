"""Vercel serverless entrypoint. Vercel's @vercel/python runtime serves the ASGI
`app` exported here; vercel.json routes all /api/* requests to this function."""
from api.main import app  # noqa: F401  (re-exported for the Vercel runtime)
