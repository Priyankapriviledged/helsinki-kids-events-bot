#!/usr/bin/env python3
"""
Helsinki-region kids' events -> Telegram notifier.

Fetches free / family events suitable for kids roughly aged 1-8 (covers
both a 19-month-old and an early-school-age child) from the Helsinki
capital region's open "Linked Events" API. This single API covers:
  - City of Helsinki events & cultural centres
  - City of Espoo events
  - City of Vantaa events (Vantaa's own event calendar is built on the
    same backend)
  - Helmet metropolitan area public libraries (Helsinki, Espoo, Vantaa,
    Kauniainen)

Docs: https://api.hel.fi/linkedevents/v1/

New events (ones not seen before) are sent to a Telegram chat via a bot.
Already-notified events are tracked in seen_events.json so nothing is
sent twice.

Facebook Events and small independent blogs (e.g. finlandforkids.com,
pientenhelsinki.fi) are NOT scraped here -- Facebook disallows automated
scraping in its Terms of Service, and the blogs don't offer structured
data. See README.md for manual-friendly ways to keep an eye on those.
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

API_URL = "https://api.hel.fi/linkedevents/v1/event/"
STATE_FILE = Path(__file__).parent / "seen_events.json"

# Municipalities to include. The API's "division" filter matches place
# divisions by name regardless of division type, so plain municipality
# names work here.
DIVISIONS = ["helsinki", "espoo", "vantaa"]

# By default the API only returns "General" (one-off) events. Recurring
# hobby/course groups -- the kind listed on harrastukset.hel.fi and
# harrastukset.vantaa.fi -- are modeled as "Course" type events in the
# same underlying database, so fetch_events() queries for both. (Both of
# those sites are confirmed to run on this API; Espoo's hobby search may
# or may not be -- worth checking the first run's results for Espoo
# hobby groups specifically.)

# Loose text searches -- intentionally broad per user preference ("loose"
# filtering), covering roughly ages 1-8 (a 19-month-old up through an
# early-school-age kid). Each query is run separately and results are
# merged & de-duplicated, since a single combined query returns weaker
# matches.
TEXT_QUERIES = [
    "lapset",         # children (fi)
    "lapsiperhe",     # families with children (fi)
    "perhe",          # family (fi)
    "vauva",          # baby (fi)
    "taapero",        # toddler (fi)
    "vauvamuskari",   # baby music class
    "muskari",        # common baby/toddler/kid music class term
    "perhekerho",     # family club
    "perhekahvila",   # family café / drop-in meetup
    "satutunti",      # story hour
    "leikkipuisto",   # playground (city-run, often has free toddler activities)
    "kids",
    "toddler",
    "baby",
    "family",
]

# How far ahead to look.
DAYS_AHEAD = 30

# Terms that suggest an event is NOT meant for the 1-8y range, used to
# trim obviously irrelevant results (e.g. senior citizen clubs that also
# contain the word "perhe" in unrelated text).
EXCLUDE_TERMS = [
    "18v", "18-vuo", "aikuisille", "senior", "eläkeläis", "ikäihmis",
    "opiskelij",  # student-focused
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_seen() -> set[str]:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except json.JSONDecodeError:
            return set()
    return set()


def save_seen(seen: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2))


def fetch_events() -> list[dict]:
    """Query the Linked Events API with several overlapping searches to
    catch events regardless of exactly how organisers tagged them.

    Runs two passes per search term:
      - "General" (one-off) events, restricted to start within the
        lookahead window, same as before.
      - "Course" (recurring hobby group) events, restricted only by
        *end* date -- a weekly hobby group may have started weeks ago
        as part of the semester and still be open for newcomers, so
        filtering by start date would wrongly exclude it.
    """
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=DAYS_AHEAD)).isoformat()

    all_events: dict[str, dict] = {}

    for text in TEXT_QUERIES:
        base_params = {
            "text": text,
            "division": ",".join(DIVISIONS),
            "sort": "start_time",
            "is_free": "true",
            "page_size": 100,
        }

        query_variants = [
            {**base_params, "event_type": "General", "start": today, "end": end},
            {**base_params, "event_type": "Course", "end": end},
        ]

        for params in query_variants:
            url = API_URL
            page_guard = 0
            while url and page_guard < 20:
                page_guard += 1
                try:
                    resp = requests.get(url, params=params, timeout=30)
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    print(f"Request failed for text={text!r} params={params}: {exc}", file=sys.stderr)
                    break

                data = resp.json()
                for ev in data.get("data", []):
                    all_events[ev["id"]] = ev

                url = (data.get("meta") or {}).get("next")
                params = None  # subsequent page URLs already include query params
                time.sleep(0.3)

    return list(all_events.values())


def event_text(ev: dict) -> str:
    name = (ev.get("name") or {})
    desc = (ev.get("short_description") or {}) or (ev.get("description") or {})
    parts = [
        name.get("fi", ""), name.get("en", ""),
        desc.get("fi", "") if isinstance(desc, dict) else "",
        desc.get("en", "") if isinstance(desc, dict) else "",
    ]
    return " ".join(p for p in parts if p).lower()


def looks_kid_relevant(ev: dict) -> bool:
    """Loose filter: exclude only the clearly-wrong-audience events."""
    text = event_text(ev)
    return not any(term in text for term in EXCLUDE_TERMS)


def is_free(ev: dict) -> bool:
    offers = ev.get("offers") or []
    if not offers:
        return True  # no price info listed usually means free
    return any(o.get("is_free") for o in offers)


def format_message(ev: dict) -> str:
    name_d = ev.get("name") or {}
    name = html.escape(name_d.get("fi") or name_d.get("en") or "Tapahtuma")

    start = (ev.get("start_time") or "")[:16].replace("T", " ")

    place_name = ""
    location = ev.get("location")
    if isinstance(location, dict):
        loc_name = location.get("name")
        if isinstance(loc_name, dict):
            place_name = loc_name.get("fi") or loc_name.get("en") or ""
    place_name = html.escape(place_name)

    link = ""
    info_url = ev.get("info_url")
    if isinstance(info_url, dict):
        link = info_url.get("fi") or info_url.get("en") or ""
    if not link:
        link = f"https://tapahtumat.hel.fi/fi/events/{ev['id']}"

    lines = [f"🧒 <b>{name}</b>"]
    if start:
        lines.append(f"🕒 {start}")
    if place_name:
        lines.append(f"📍 {place_name}")
    lines.append(link)
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Telegram send failed: {exc}", file=sys.stderr)
        return False

    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
    return True


def main() -> None:
    seen = load_seen()
    events = fetch_events()
    print(f"Fetched {len(events)} candidate events")

    new_events = [
        ev for ev in events
        if ev["id"] not in seen and looks_kid_relevant(ev) and is_free(ev)
    ]
    # Oldest/soonest first
    new_events.sort(key=lambda e: e.get("start_time") or "")
    print(f"{len(new_events)} new events to send")

    sent_ok = 0
    for ev in new_events:
        if send_telegram(format_message(ev)):
            sent_ok += 1
            seen.add(ev["id"])
        time.sleep(1)  # be gentle with Telegram's rate limits

    save_seen(seen)
    print(f"Sent {sent_ok}/{len(new_events)} messages. State saved with {len(seen)} known events.")


if __name__ == "__main__":
    main()
