# Helsinki-area kids' events → Telegram bot

Sends new free/family events (Helsinki, Espoo, Vantaa + Helmet libraries)
for roughly your child's age group to a Telegram chat, on a schedule,
for free, with no server to maintain.

## How it works

- `scraper.py` queries the capital region's open **Linked Events API**
  (`api.hel.fi/linkedevents`), which is the actual data source behind
  tapahtumat.hel.fi, Espoo's and Vantaa's event calendars, and the
  Helmet library event listings. It's structured JSON, so this is far
  more reliable than parsing HTML pages.
- It filters for free events over the next 30 days, does a light
  keyword screen to drop obviously wrong-audience events (senior clubs,
  18+ events, etc.), and sends anything new to your Telegram chat.
- `seen_events.json` remembers what's already been sent, so you won't
  get duplicates. GitHub Actions commits the updated file back to the
  repo after each run, so state persists between runs.

## One-time setup

### 1. Get your Telegram chat ID
You already have a bot + token. You also need the **chat ID** to send to
(this can be your own DM with the bot, or a group):
1. Send any message to your bot (or add it to a group and send a message there).
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Look for `"chat":{"id": ...}` in the response — that number is your chat ID.

### 2. Create a GitHub repository
- Create a new **private** repo (recommended, since it'll contain your
  chat ID as a secret anyway) and push these files to it.

### 3. Add secrets
In the repo: **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` — your bot's token
- `TELEGRAM_CHAT_ID` — the chat ID from step 1

### 4. Enable the workflow
The workflow in `.github/workflows/check_events.yml` runs automatically
twice a day (06:00 and 14:00 UTC — edit the `cron` line to change
timing) and can also be triggered manually from the repo's **Actions**
tab via "Run workflow".

That's it — no server, no hosting costs, GitHub Actions' free tier
comfortably covers a couple of runs a day.

## Testing locally (optional)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
python scraper.py
```

The first run will likely send a burst of messages (everything currently
matching, since nothing's been "seen" yet) — that's expected and a good
way to check filtering looks right. After that, only new events trigger
messages.

## Tuning the filter

Open `scraper.py` and adjust:
- `TEXT_QUERIES` — the Finnish/English search terms used to find events.
  Add terms like `"muskari"`, `"satutunti"` (story hour), `"askartelu"`
  (crafts), etc. as you learn what's out there.
- `EXCLUDE_TERMS` — words that mean "skip this one."
- `DAYS_AHEAD` — how far ahead to search (default 30 days).
- Filtering is currently **loose** by design (per your preference) —
  it includes general family/kids events for roughly ages 1-8, not just
  ones explicitly tagged for a specific age, so you'll want to skim.

## About Facebook Events

This is a deliberate choice, not a gap: Facebook's Terms of Service
prohibit automated scraping, and technically it requires a logged-in
session and JavaScript rendering that breaks every time Facebook
tweaks its frontend — so it's excluded from this scraper. Two
lower-effort alternatives if Facebook groups/pages are important to
you:
- **Follow specific pages/groups directly** in the Telegram or Facebook
  app and turn on notifications for them — for pages that post free kids'
  events regularly (day-care associations, local parish family clubs,
  neighborhood parent groups), this is often more reliable than any
  scraper, since organizers frequently post to Facebook *only*, free,
  and zero maintenance.
- **ScrapeCreators' free tier** (scrapecreators.com/facebookEvents-api)
  offers 100 free, non-expiring credits and pay-as-you-go pricing after
  that, if you ever want structured Facebook event data without a
  monthly commitment. It's an unofficial API (like any Facebook scraper,
  paid or not), so that's worth knowing before signing up. If you decide
  to go this route later, this scraper's dedup/notify pipeline can be
  extended to pull from it fairly easily — just ask.

## Hobby groups (harrastukset.hel.fi / harrastukset.vantaa.fi / Espoo)

Recurring hobby groups -- the kind listed on Helsinki's and Vantaa's
"hobby search" sites -- turned out to be stored in the *same* Linked
Events database as the one-off events, just tagged as `Course` type
instead of `General`. So `scraper.py` now queries for both types, with
Course-type events filtered only by end date (not start date), since a
weekly hobby group may have started weeks ago as part of the semester
and still be open for newcomers to join.

- **Helsinki & Vantaa**: confirmed to work this way (their hobby sites
  are built on this API, per their own open-source repos).
- **Espoo**: espoo.fi/harrastushaku is a separate-looking widget and I
  couldn't confirm from here whether it draws from the same database.
  Espoo's regular events are imported into Linked Events, so there's a
  good chance hobby groups are too — worth checking your first run's
  results specifically for Espoo hobby groups. If they're missing, this
  would need a dedicated scraper for espoo.fi/harrastushaku instead
  (more fragile, since it appears to be a JS widget without a public
  API) — let me know if you hit this and want it built.

## Other sources not yet included

These don't have a structured API, so they'd need HTML scraping (more
fragile, breaks when the site redesigns) — happy to add any of them if
you want:
- `pientenhelsinki.fi`, `finlandforkids.com` (independent blogs)
