"""Re-pin requirements.txt from uv.lock — the two files hold the same versions by hand.

There are two dependency manifests and only one resolver. `uv.lock` is the resolved truth
for everything (dev included); `requirements.txt` is the RUNTIME SUBSET that Vercel's Python
builder installs into the function — deliberately without alembic/uvicorn/ruff/pytest, which
never run inside a request. Nothing derives one from the other: `uv export` would drag
alembic and uvicorn in, because they are real `[project].dependencies`, so the package LIST
in requirements.txt is a curated choice a human made.

The versions are not a choice. This script keeps the curated list exactly as it is and
rewrites each `==` pin to whatever uv.lock resolved, which is the half that silently rots
when a lockfile bump lands alone — the Vercel function then ships a version nobody reviewed.

  python scripts/sync_requirements.py           # rewrite the pins
  python scripts/sync_requirements.py --check   # exit 1 if any pin has drifted (CI)

A package in requirements.txt that uv.lock has never heard of is an error, not a skip: it
means the runtime installs something the resolver never saw, which is the exact failure the
lockfile exists to prevent.
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
REQS = ROOT / "requirements.txt"

# `name[extra1,extra2]==version` — extras are part of the curated list (psycopg[binary]),
# so they survive untouched; only the version on the right of `==` is ours to rewrite.
PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?P<extras>\[[^\]]*\])?==(?P<version>\S+)\s*$")


def locked_versions():
    """{normalized package name: version} for every package uv resolved."""
    lock = tomllib.loads(LOCK.read_text())
    return {normalize(p["name"]): p["version"] for p in lock.get("package", [])}


def normalize(name):
    """PEP 503 name normalization — requirements.txt says PyJWT, uv.lock says pyjwt."""
    return re.sub(r"[-_.]+", "-", name).lower()


def sync(check):
    versions = locked_versions()
    out, drifted, unknown = [], [], []

    for line in REQS.read_text().splitlines(keepends=True):
        m = PIN.match(line)
        if not m:
            out.append(line)          # comments, blanks, anything unpinned: left alone
            continue
        name, extras, pinned = m["name"], m["extras"] or "", m["version"]
        locked = versions.get(normalize(name))
        if locked is None:
            unknown.append(name)
            out.append(line)
            continue
        if locked != pinned:
            drifted.append((name, pinned, locked))
        out.append(f"{name}{extras}=={locked}\n")

    if unknown:
        print(f"not in uv.lock: {', '.join(unknown)}", file=sys.stderr)
        print("requirements.txt pins a package the resolver never saw — add it to "
              "pyproject.toml [project].dependencies and re-lock, or drop it.", file=sys.stderr)
        return 1

    if not drifted:
        print("requirements.txt is in sync with uv.lock")
        return 0

    for name, pinned, locked in drifted:
        print(f"{name}: {pinned} -> {locked}")

    if check:
        print("\nrequirements.txt has drifted from uv.lock. Run `make sync-requirements` "
              "and commit the result — the Vercel function installs requirements.txt, so a "
              "lockfile-only bump never reaches production.", file=sys.stderr)
        return 1

    REQS.write_text("".join(out))
    print(f"\nrewrote {len(drifted)} pin(s) in requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(sync(check="--check" in sys.argv[1:]))
