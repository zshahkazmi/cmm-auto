"""Directory -> outreach bridge for the cmm-outreach repo.

  python tools/pull_directory.py pull   --url <EXEC> --token <T> \
      [--limit 60] [--leads leads/auto-current.csv] [--keys auto-keys.json]
  python tools/pull_directory.py report --url <EXEC> --token <T> \
      --keys auto-keys.json --results results/auto-123.csv

pull:   asks the directory endpoint (Apps Script) for businesses that
        have a website, were never handed to outreach, and whose domain
        was never contacted on the main lead sheet. Writes the leads CSV
        for formscout plus a keys file mapping each lead to its
        directory place_key.
report: after a formscout run, records every processed business in the
        directory's Outreach ledger (with its outcome) so it is never
        pulled again. Businesses missing from the results file are NOT
        reported — they stay pending and are retried by a later run.

Transport follows the Apps Script rules: the script executes on the
first request and its JSON result is served to the redirect-follow GET;
calls are retried with backoff on non-JSON replies.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from urllib.parse import urlparse, urlunparse

RETRY_DELAYS = (0, 10, 30, 60)


def _parse(r, what):
    try:
        data = r.json()
    except ValueError:
        snippet = (r.text or "")[:200].replace("\n", " ")
        raise RuntimeError(f"{what}: non-JSON reply (HTTP {r.status_code}): {snippet!r}")
    if not isinstance(data, dict) or "ok" not in data:
        raise RuntimeError(f"{what}: unexpected reply: {str(data)[:200]!r}")
    return data


def _with_retries(fn, what):
    last = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return fn()
        except Exception as e:
            last = e
            if attempt < len(RETRY_DELAYS) - 1:
                print(f"{what} failed ({type(e).__name__}: {e}); retrying...")
    raise RuntimeError(f"{what}: giving up after {len(RETRY_DELAYS)} attempts: {last}")

def _check_config(url, token):
    if not url or not url.startswith("http"):
        raise SystemExit("CONFIG ERROR: the API URL is empty or invalid. "
                         "In the cmm-outreach repo, Settings -> Secrets and "
                         "variables -> Actions -> Repository secrets must "
                         "contain MAPSCOUT_API_URL (the Apps Script /exec "
                         "link) and MAPSCOUT_API_TOKEN.")
    if not token:
        raise SystemExit("CONFIG ERROR: the API token is empty. Check the "
                         "MAPSCOUT_API_TOKEN repository secret in cmm-outreach.")


def clean_url(u: str) -> str:
    p = urlparse(u or "")
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def cmd_pull(args) -> int:
    _check_config(args.url, args.token)
    import requests

    def once():
        r = requests.get(args.url, params={"token": args.token,
                                           "action": "pending",
                                           "limit": args.limit}, timeout=180)
        data = _parse(r, "directory pending")
        if not data.get("ok"):
            raise RuntimeError(f"directory pending error: {data}")
        return data["rows"]

    rows = _with_retries(once, "directory pending")
    with open(args.leads, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "website", "postcode"])
        w.writeheader()
        for row in rows:
            w.writerow({"name": row["name"], "website": clean_url(row["website"]),
                        "postcode": row["postcode"]})
    with open(args.keys, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    print(f"PULLED {len(rows)} businesses -> {args.leads}")
    return 0


def cmd_report(args) -> int:
    _check_config(args.url, args.token)
    import requests

    keys = json.load(open(args.keys, encoding="utf-8"))
    outcomes = {}
    with open(args.results, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            outcomes[(r.get("domain") or "").strip().lower()] = r.get("outcome", "")
    outreach, skipped = [], 0
    for k in keys:
        outcome = outcomes.get((k["domain"] or "").strip().lower())
        if outcome is None:
            skipped += 1
            continue
        outreach.append({"place_key": k["place_key"], "domain": k["domain"],
                         "name": k["name"], "outcome": outcome})
    if not outreach:
        print(f"nothing to report ({skipped} leads absent from results; left pending)")
        return 0

    def once():
        r = requests.post(args.url, json={"token": args.token,
                                          "outreach": outreach}, timeout=180)
        data = _parse(r, "directory report")
        if not data.get("ok"):
            raise RuntimeError(f"directory report error: {data}")
        return data

    data = _with_retries(once, "directory report")
    print(f"REPORTED {data.get('outreach_added', len(outreach))} businesses "
          f"to the Outreach ledger ({skipped} left pending)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pull_directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("pull")
    sp.add_argument("--url", required=True)
    sp.add_argument("--token", required=True)
    sp.add_argument("--limit", type=int, default=60)
    sp.add_argument("--leads", default="leads/auto-current.csv")
    sp.add_argument("--keys", default="auto-keys.json")
    sp.set_defaults(fn=cmd_pull)
    sp = sub.add_parser("report")
    sp.add_argument("--url", required=True)
    sp.add_argument("--token", required=True)
    sp.add_argument("--keys", default="auto-keys.json")
    sp.add_argument("--results", required=True)
    sp.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
