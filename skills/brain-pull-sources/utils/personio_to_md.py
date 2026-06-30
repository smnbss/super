#!/usr/bin/env python3
from __future__ import annotations
"""
Personio staff roster -> src/personio/ exporter.

Personio exposes the full employee roster via the **v1** REST API
(`GET /v1/company/employees`), which returns every employee with a rich,
labelled attribute set (position, department, supervisor, hire date, status,
plus any company-defined dynamic attributes such as Team / Office). That is the
richest source for the people lookup the brain depends on ([[team-members]]),
so we build the roster from it.

Auth (v1, client-credentials):
    POST /v1/auth { client_id, client_secret } -> { success, data: { token } }
    The bearer token *rotates* on every subsequent call — each response carries a
    fresh `Authorization: Bearer <token>` header which we reuse for the next page.

Output (src/personio/):
    personio-staff.tsv — one row per employee, canonical columns (same schema as
                  the legacy roster export so existing consumers keep working).

Attributes are flattened **by label** (case-insensitive), so standard and
company-specific dynamic attributes are picked up the same way and the exporter
keeps working if Personio attribute internal ids change.

Usage:
    python personio_to_md.py [--base-url https://api.personio.de]
                             [--client ID] [--secret SECRET]
                             [--limit 200] [--list] [--verbose]

Environment (first non-empty wins):
    PERSONIO_CLIENT / PERSONIO_CLIENT_ID / personio_client   — API client id
    PERSONIO_SECRET / PERSONIO_CLIENT_SECRET / personio_secret — API client secret
    PERSONIO_BASE_URL                                         — default https://api.personio.de
"""

import argparse
import json
import os
import subprocess as _sp
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


# -- Project root (use git to find repo root, not relative path) --------------

PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip() or os.getcwd()


# -- Load .env from project root ----------------------------------------------

def load_dotenv():
    """Load key=value pairs from .env.local in the project root (no overwrite)."""
    env_path = os.path.join(PROJECT_ROOT, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "personio")
TSV_PATH = os.path.join(OUTPUT_BASE, "personio-staff.tsv")

DEFAULT_BASE_URL = os.environ.get("PERSONIO_BASE_URL", "https://api.personio.de").rstrip("/")
USER_AGENT = "curl/8.7.1"

# Canonical TSV columns -> the attribute labels we accept for each (lowercased).
# Order here is the column order in staff.tsv (matches the legacy export).
COLUMNS: list[tuple[str, list[str]]] = [
    ("ID",                ["id"]),
    ("First Name",        ["first name"]),
    ("Last Name",         ["last name"]),
    ("Email",             ["email", "email address"]),
    ("Position",          ["position"]),
    ("Department",        ["department"]),
    ("Team",              ["team"]),
    ("Office",            ["office", "office location"]),
    ("Hire Date",         ["hire date"]),
    ("Status",            ["status"]),
    ("Supervisor",        ["supervisor"]),
    ("Contract End Date", ["contract end date", "contract ends"]),
    ("Occupation Type",   ["occupation type", "employment type"]),
]
DATE_COLUMNS = {"Hire Date", "Contract End Date"}


def resolve_creds(cli_client: str, cli_secret: str) -> tuple[str, str]:
    client = (
        cli_client
        or os.environ.get("PERSONIO_CLIENT")
        or os.environ.get("PERSONIO_CLIENT_ID")
        or os.environ.get("personio_client")
        or ""
    )
    secret = (
        cli_secret
        or os.environ.get("PERSONIO_SECRET")
        or os.environ.get("PERSONIO_CLIENT_SECRET")
        or os.environ.get("personio_secret")
        or ""
    )
    return client.strip(), secret.strip()


# -- API ----------------------------------------------------------------------

def authenticate(base_url: str, client: str, secret: str) -> str:
    """POST /v1/auth -> bearer token."""
    body = json.dumps({"client_id": client, "client_secret": secret}).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/auth",
        data=body,
        headers={"Accept": "application/json",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"ERROR: Personio auth failed (HTTP {e.code}): {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"ERROR: could not reach Personio ({base_url}): {e.reason}")
    if not data.get("success") or not (data.get("data") or {}).get("token"):
        raise SystemExit(f"ERROR: Personio auth returned no token: {json.dumps(data)[:300]}")
    return data["data"]["token"]


def get_page(base_url: str, token: str, limit: int, offset: int) -> tuple[dict, str]:
    """GET one page of /v1/company/employees. Returns (json, rotated_token)."""
    url = f"{base_url}/v1/company/employees?limit={limit}&offset={offset}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                # Personio rotates the bearer token on each call.
                new_auth = resp.headers.get("Authorization", "")
                rotated = new_auth.split(" ", 1)[1] if new_auth.lower().startswith("bearer ") else token
                return json.loads(resp.read().decode("utf-8")), rotated
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"ERROR: /company/employees failed (HTTP {e.code}): {detail}")
    raise SystemExit("ERROR: /company/employees rate-limited after retries")


def fetch_employees(base_url: str, token: str, limit: int, verbose: bool) -> list[dict]:
    """Page through every employee."""
    out: list[dict] = []
    offset = 0
    while True:
        page, token = get_page(base_url, token, limit, offset)
        chunk = page.get("data") or []
        out.extend(chunk)
        total = (page.get("metadata") or {}).get("total_elements")
        if verbose:
            print(f"  fetched {len(out)}"
                  + (f"/{total}" if total is not None else "")
                  + " employees…")
        if len(chunk) < limit:
            break
        offset += limit
        if total is not None and offset >= total:
            break
    return out


# -- Rendering ----------------------------------------------------------------

def render_value(val) -> str:
    """Flatten a v1 attribute value to a display string."""
    if val is None or val == "":
        return ""
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    if isinstance(val, list):
        return ", ".join(filter(None, (render_value(v) for v in val)))
    if isinstance(val, dict):
        # Nested object: {"type": ..., "attributes": {...}}
        attrs = val.get("attributes", val)
        if isinstance(attrs, dict):
            # Employee-like (supervisor): first_name + last_name
            fn = attrs.get("first_name")
            ln = attrs.get("last_name")
            if fn or ln:
                fn = render_value(fn.get("value") if isinstance(fn, dict) else fn)
                ln = render_value(ln.get("value") if isinstance(ln, dict) else ln)
                full = f"{fn} {ln}".strip()
                if full:
                    return full
            # Department / cost-center-like: a name field
            for key in ("name", "label"):
                if attrs.get(key):
                    return render_value(attrs[key])
        return ""
    return str(val)


def fmt_date(raw: str) -> str:
    """ISO date/datetime -> '19 May 2025' to match the legacy roster format."""
    if not raw:
        return ""
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(s[:19] if "T" in s else s[:10], fmt[:19] if "T" in s else fmt)
            return f"{d.day} {d:%b %Y}"
        except ValueError:
            continue
    return s


def employee_to_labelmap(emp: dict) -> dict[str, object]:
    """Build {label_lower: raw_value} from a v1 employee's attribute dict."""
    attrs = (emp.get("attributes") or {})
    label_map: dict[str, object] = {}
    for _key, meta in attrs.items():
        if not isinstance(meta, dict):
            continue
        label = str(meta.get("label", "")).strip().lower()
        if label:
            label_map[label] = meta.get("value")
    return label_map


def employee_to_row(emp: dict) -> dict[str, str]:
    label_map = employee_to_labelmap(emp)
    row: dict[str, str] = {}
    for col, aliases in COLUMNS:
        raw = ""
        for alias in aliases:
            if alias in label_map:
                raw = label_map[alias]
                break
        text = render_value(raw)
        if col in DATE_COLUMNS:
            text = fmt_date(text)
        if col == "Status" and text:
            text = text[:1].upper() + text[1:]
        row[col] = text.replace("\t", " ").replace("\n", " ").strip()
    return row


def write_tsv(rows: list[dict]):
    headers = [c for c, _ in COLUMNS]
    lines = ["\t".join(headers)]
    for r in rows:
        lines.append("\t".join(r.get(h, "") for h in headers))
    with open(TSV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# -- Main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Export the WeRoad Personio staff roster to src/personio/.")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="Personio API base (default https://api.personio.de).")
    ap.add_argument("--client", default="", help="API client id (else PERSONIO_CLIENT env).")
    ap.add_argument("--secret", default="", help="API client secret (else PERSONIO_SECRET env).")
    ap.add_argument("--limit", type=int, default=200, help="Page size (default 200).")
    ap.add_argument("--include-inactive", action="store_true",
                    help="Keep inactive/ex-employees (default: active staff only — "
                         "active, leave, onboarding).")
    ap.add_argument("--list", action="store_true",
                    help="Print current export status and exit.")
    ap.add_argument("--verbose", action="store_true")
    # pull_sources passes the tool name itself as a stray positional for argless
    # source lines (`bin/personio_to_md personio_to_md`); ignore any such extras.
    args, _unknown = ap.parse_known_args()

    if args.list:
        rel = os.path.relpath(TSV_PATH, PROJECT_ROOT)
        if os.path.isfile(TSV_PATH):
            n = sum(1 for _ in open(TSV_PATH)) - 1
            mt = datetime.fromtimestamp(os.path.getmtime(TSV_PATH)).strftime("%Y-%m-%d %H:%M")
            print(f"{rel} — {n} employees, last exported {mt}")
        else:
            print(f"{rel} — not yet exported")
        return

    client, secret = resolve_creds(args.client, args.secret)
    if not client or not secret:
        print("ERROR: Personio credentials required. Set PERSONIO_CLIENT and "
              "PERSONIO_SECRET in .env.local (or pass --client/--secret).",
              file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_BASE, exist_ok=True)
    print(f"Authenticating to {args.base_url} …")
    token = authenticate(args.base_url, client, secret)
    print("Fetching employees …")
    employees = fetch_employees(args.base_url, token, args.limit, args.verbose)
    if not employees:
        print("WARNING: Personio returned 0 employees — leaving existing export untouched.",
              file=sys.stderr)
        sys.exit(1)

    rows = [employee_to_row(e) for e in employees]
    rows.sort(key=lambda r: (r.get("Last Name", "").lower(), r.get("First Name", "").lower()))

    total_fetched = len(rows)
    if not args.include_inactive:
        rows = [r for r in rows if r.get("Status", "").strip().lower() != "inactive"]
        dropped = total_fetched - len(rows)
        if dropped:
            print(f"Filtered out {dropped} inactive employees "
                  f"(use --include-inactive to keep them).")

    write_tsv(rows)

    # Surface which canonical columns came back empty (likely a credential scope gap).
    empty_cols = [c for c, _ in COLUMNS
                  if not any(r.get(c) for r in rows)]
    print(f"Wrote {len(rows)} employees -> "
          f"{os.path.relpath(TSV_PATH, PROJECT_ROOT)}")
    if empty_cols:
        print("NOTE: no data for columns "
              f"{empty_cols} — these attributes may not be enabled on the "
              "API credential's readable-attributes scope in Personio.")


if __name__ == "__main__":
    main()
