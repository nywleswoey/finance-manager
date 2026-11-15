"""The FastAPI app (`server.main:app`; api/index.py re-exports it for Vercel).

  main           composition root only: app object, middleware, the deny-by-default
                 `auth_gate`, /api/health, the built SPA mount (last)
  auth           Google OAuth router (/api/auth/*) and the session cookie
  refresh        price refresh: the UI's POST /api/refresh-prices and the Vercel cron GET
  posthog_proxy  same-origin /ingest/* reverse proxy for posthog-js
  routes/        one router per product — see routes/__init__.py
"""
