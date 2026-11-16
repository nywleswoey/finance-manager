"""The FastAPI app (`server.main:app`; api/index.py re-exports it for Vercel).

  main     composition root only: app object, middleware, the deny-by-default `auth_gate`,
           health / refresh-prices / cron, PostHog proxy, the built SPA mount (last)
  auth     Google OAuth router (/api/auth/*) and the session cookie
  routes/  one router per product — see routes/__init__.py
"""
