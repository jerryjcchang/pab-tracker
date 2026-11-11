#!/usr/bin/env python3
"""Check whether LEGO Pick-a-Brick elements are in stock; push a notification via ntfy.sh
only when one flips from out-of-stock to in-stock.

Uses the same GraphQL endpoint the Pick-a-Brick page itself calls
(https://www.lego.com/api/graphql/PickABrickQuery). Each result has an `availability`
field that is either "AVAILABLE" or "OUT_OF_STOCK".

Env vars:
  PAB_ELEMENT_ID   required; one ID or several separated by commas/spaces,
                   e.g. "6615702" or "6615702, 300126, 4211399"
  NTFY_TOPIC       required, your private ntfy topic name
  PAB_LOCALE       optional, default "en-us"
  DEBUG            optional, set to 1 to print the item data found
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ELEMENT_IDS = list(
    dict.fromkeys(i for i in re.split(r"[,\s]+", os.environ["PAB_ELEMENT_ID"]) if i)
)
NTFY_TOPIC = os.environ["NTFY_TOPIC"].strip()
LOCALE = os.environ.get("PAB_LOCALE", "en-us").strip().lower()
STATE_FILE = "state.json"
DEBUG = os.environ.get("DEBUG") == "1"
DELAY_SECONDS = 2  # pause between requests to be polite

API_URL = "https://www.lego.com/api/graphql/PickABrickQuery"
QUERY = (
    "query PickABrickQuery($input: ElementQueryInput!) { "
    "searchElements(input: $input) { "
    "results { id name availability maxOrderQuantity deliveryChannel "
    "price { formattedAmount formattedValue } } total count } }"
)


def x_locale():
    lang, _, region = LOCALE.partition("-")
    return f"{lang}-{region.upper()}" if region else lang


def page_url(element_id):
    return (
        f"https://www.lego.com/{LOCALE}/pick-and-build/pick-a-brick?"
        + urllib.parse.urlencode({"query": element_id})
    )


def fetch_results(element_id):
    body = {
        "operationName": "PickABrickQuery",
        "variables": {
            "input": {
                "page": 1,
                "perPage": 50,
                "sort": {"key": "RELEVANCE", "direction": "DESC"},
                "availability": ["AVAILABLE", "OUT_OF_STOCK"],
                "query": element_id,
                "fetchSiblings": True,
            }
        },
        "query": QUERY,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-locale": x_locale(),
            "Origin": "https://www.lego.com",
            "Referer": page_url(element_id),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        snippet = e.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from LEGO (possibly blocked): {snippet!r}")
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(data['errors'])[:300]}")
    try:
        return data["data"]["searchElements"]["results"]
    except (KeyError, TypeError):
        raise RuntimeError(f"Unexpected response shape: {json.dumps(data)[:300]}")


def in_stock(item):
    return bool(item) and item.get("availability") == "AVAILABLE"


def notify(element_id, item):
    name = item.get("name", element_id)
    price = (item.get("price") or {}).get("formattedAmount", "")
    message = " ".join(f"{name} {price} is back in stock on Pick-a-Brick!".split())
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode(),
        headers={
            "Title": "LEGO restock",
            "Priority": "high",
            "Tags": "bricks",
            "Click": page_url(element_id),
        },
    )
    urllib.request.urlopen(req, timeout=30).close()


def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    # Ignore the old single-item format ({"in_stock": ...}).
    return {k: bool(v) for k, v in data.items() if k.isdigit()}


def check_one(element_id, state):
    """Return current in-stock bool. Raises if the lookup failed."""
    results = fetch_results(element_id)
    item = next((r for r in results if str(r.get("id")) == element_id), None)

    if DEBUG:
        print(f"[{element_id}] item:", json.dumps(item, indent=2))
    if item is None:
        print(f"[{element_id}] not in results (treating as out of stock)")

    now = in_stock(item)
    was = state.get(element_id, False)
    print(f"[{element_id}] {(item or {}).get('name', '?')}: in_stock={now} (previously {was})")
    if now and not was:
        notify(element_id, item)
        print(f"[{element_id}] notification sent")
    return now


def main():
    if not ELEMENT_IDS:
        raise SystemExit("PAB_ELEMENT_ID is empty")
    state = load_state()
    new_state = dict(state)  # failed checks keep their previous value
    failures = []

    for n, element_id in enumerate(ELEMENT_IDS):
        if n:
            time.sleep(DELAY_SECONDS)
        try:
            new_state[element_id] = check_one(element_id, state)
        except Exception as e:
            failures.append(element_id)
            print(f"[{element_id}] check failed: {e}", file=sys.stderr)

    # Only keep IDs still being tracked.
    new_state = {k: v for k, v in new_state.items() if k in ELEMENT_IDS}
    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, indent=2, sort_keys=True)

    if failures:
        print(
            f"{len(failures)} of {len(ELEMENT_IDS)} checks failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()