#!/usr/bin/env python3
"""Check whether a LEGO Pick-a-Brick element is in stock; push a notification via ntfy.sh
only when it flips from out-of-stock to in-stock.

Env vars:
  PAB_ELEMENT_ID   required, e.g. "300121" (the element/design ID from the PaB listing)
  NTFY_TOPIC       required, your private ntfy topic name
  PAB_LOCALE       optional, default "en-US"
  DEBUG            optional, set to 1 to print the raw item found
"""
import json
import os
import sys
import urllib.request

ELEMENT_ID = os.environ["PAB_ELEMENT_ID"].strip()
NTFY_TOPIC = os.environ["NTFY_TOPIC"].strip()
LOCALE = os.environ.get("PAB_LOCALE", "en-US")
STATE_FILE = "state.json"
DEBUG = os.environ.get("DEBUG") == "1"

URL = "https://www.lego.com/api/graphql/PickABrickQuery"
QUERY = """
query PickABrickQuery($input: ElementQueryInput!) {
  elements(input: $input) {
    results {
      id
      name
      deliveryChannel
      maxOrderQuantity
      price { formattedAmount }
      facets { name }
    }
  }
}
"""


def fetch_item():
    body = {
        "operationName": "PickABrickQuery",
        "variables": {"input": {"query": ELEMENT_ID, "page": 1, "perPage": 20}},
        "query": QUERY,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-locale": LOCALE,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    for item in data["data"]["elements"]["results"]:
        if str(item.get("id")) == ELEMENT_ID:
            return item
    return None


def in_stock(item):
    """Best-effort: LEGO signals availability via a few fields; adjust after checking DEBUG output."""
    if item is None:
        return False
    for key in ("inStock", "available", "canAddToBag"):
        if key in item:
            return bool(item[key])
    if item.get("deliveryChannel") == "pab" and (item.get("maxOrderQuantity") or 0) > 0:
        return True
    return False


def notify(item):
    name = item.get("name", ELEMENT_ID)
    price = (item.get("price") or {}).get("formattedAmount", "")
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=f"{name} {price} is back in stock on Pick-a-Brick!".encode(),
        headers={
            "Title": "LEGO restock",
            "Priority": "high",
            "Tags": "bricks",
            "Click": "https://www.lego.com/pick-and-build/pick-a-brick",
        },
    )
    urllib.request.urlopen(req, timeout=30).close()


def main():
    item = fetch_item()
    if DEBUG:
        print("raw item:", json.dumps(item, indent=2))
    now = in_stock(item)

    try:
        with open(STATE_FILE) as f:
            was = json.load(f).get("in_stock", False)
    except FileNotFoundError:
        was = False

    print(f"element {ELEMENT_ID}: in_stock={now} (previously {was})")
    if now and not was:
        notify(item)
        print("notification sent")

    with open(STATE_FILE, "w") as f:
        json.dump({"in_stock": now}, f)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"check failed: {e}", file=sys.stderr)
        sys.exit(1)
