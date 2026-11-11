# LEGO Pick-a-Brick restock notifier

Checks one Pick-a-Brick element every ~10 minutes on GitHub Actions and sends a push
notification through ntfy.sh when it goes from out of stock to in stock.

## Setup

1. **Find the element ID.** On lego.com Pick-a-Brick, open the piece. The 6-7 digit number
   shown as the "element ID" (or in the URL/search box) is what you need.
2. **Pick a private ntfy topic.** Something unguessable, e.g. `lego-restock-k3x9q2`.
   Install the ntfy app on your phone and subscribe to that topic.
3. **Create a new GitHub repo** and push these files (`check_pab.py`, `.github/workflows/check.yml`).
4. In the repo go to Settings, Secrets and variables, Actions:
   - Variables tab: add `PAB_ELEMENT_ID` = your element ID
   - Secrets tab: add `NTFY_TOPIC` = your topic name
5. Go to the Actions tab, select "Check Pick-a-Brick" and click **Run workflow**.
   That manual run prints the raw item (DEBUG on) so you can confirm the piece was found
   and see which field reflects stock.

## Things to verify on the first run

- `check_pab.py` uses LEGO's GraphQL endpoint as I remember it. I couldn't test it from my
  sandbox, so the query fields and the `in_stock()` logic may need small tweaks. If the first
  run fails or the raw item looks different, send me the log output and I'll adjust.
- GitHub scheduled workflows are best effort. Expect 10-15 minute gaps, and GitHub pauses
  schedules on repos with no activity for 60 days.
- Be polite: keep the interval at 10 minutes or more.
