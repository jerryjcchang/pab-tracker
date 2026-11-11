#!/usr/bin/env python3
"""Check whether LEGO Pick-a-Brick elements are in stock; push a notification via ntfy.sh
only when one flips from out-of-stock to in-stock.

LEGO renders Pick-a-Brick search results on the server and embeds schema.org JSON-LD in the
page, including an `availability` field per product. We fetch the search page for each element
ID and read that field.

Env vars:
  PAB_ELEMENT_ID   required; one ID or several separated by commas/spaces,
                   e.g. "6615702" or "6615702, 300126, 4211399"
  NTFY_TOPIC       required, your private ntfy topic name
  PAB_LOCALE       optional, default "en-us"
  DEBUG            optional, set to 1 to print the product data found
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

LD_JSON = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)


def page_url(element_id):
    return (
        f"https://www.lego.com/{LOCALE}/pick-and-build/pick-a-brick?"
        + urllib.parse.urlencode({"query": element_id})
    )


def fetch_html(element_id):
    req = urllib.request.Request(
        page_url(element_id),
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        snippet = e.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from LEGO (possibly blocked): {snippet!r}")


def find_product(html, element_id):
    """Return (product_dict_or_None, saw_item_list)."""
    saw_list = False
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            saw_list = True
            for entry in data.get("itemListElement", []):
                if str(entry.get("sku")) == element_id:
                    return entry, saw_list
    return None, saw_list


def in_stock(product):
    if not product:
        return False
    availability = (product.get("offers") or {}).get("availability", "")
    return availability.rsplit("/", 1)[-1] in ("InStock", "LimitedAvailability")


def notify(element_id, product):
    name = product.get("name", element_id)
    price = (product.get("offers") or {}).get("price")
    price_text = f"${price}" if price is not None else ""
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=f"{name} {price_text} is back in stock on Pick-a-Brick!".replace("  ", " ").encode(),
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


def check_one(element_id):
    """Return current in-stock bool. Raises if the page couldn't be read."""
    html = fetch_html(element_id)
    product, saw_list = find_product(html, element_id)

    if not saw_list:
        # No results block at all: likely a bot-challenge page or a layout change,
        # not a genuine "out of stock". Fail loudly so state isn't overwritten.
        title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        raise RuntimeError(
            "Could not find product data on the page "
            f"(title: {title.group(1).strip() if title else 'n/a'}, {len(html)} bytes). "
            "LEGO may be blocking this request or the page layout changed."
        )

    if DEBUG:
        print(f"[{element_id}] product:", json.dumps(product, indent=2))
    if product is None:
        print(f"[{element_id}] not in results (treating as out of stock)")

    now = in_stock(product)
    was = STATE.get(element_id, False)
    print(f"[{element_id}] {(product or {}).get('name', '?')}: in_stock={now} (previously {was})")
    if now and not was:
        notify(element_id, product)
        print(f"[{element_id}] notification sent")
    return now


STATE = {}


def main():
    global STATE
    if not ELEMENT_IDS:
        raise SystemExit("PAB_ELEMENT_ID is empty")
    STATE = load_state()
    new_state = dict(STATE)  # failed checks keep their previous value
    failures = []

    for n, element_id in enumerate(ELEMENT_IDS):
        if n:
            time.sleep(DELAY_SECONDS)
        try:
            new_state[element_id] = check_one(element_id)
        except Exception as e:
            failures.append(element_id)
            print(f"[{element_id}] check failed: {e}", file=sys.stderr)

    # Only keep IDs still being tracked.
    new_state = {k: v for k, v in new_state.items() if k in ELEMENT_IDS}
    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, indent=2, sort_keys=True)

    if failures:
        print(f"{len(failures)} of {len(ELEMENT_IDS)} checks failed: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
