# 🔔 Website Watcher

Monitors any number of webpages for changes, emails you when something
changes, and publishes a live status dashboard via GitHub Pages.

Currently configured to watch:
- **Federal Grant #362005** — grants.gov posting
- **HUD RBC Research Page** — huduser.gov/portal/rbc/research.html

## How it works

1. A GitHub Action runs once a day (13:00 UTC / 9:00 AM Eastern)
2. It loops through every site in `websites.json`, fetches each page, and
   extracts either the full page text or a specific anchored section
3. Compares a hash of the extracted text against the saved snapshot in
   `snapshots/`
4. If a site changed → sends an email alert with the new + old content
5. Writes `status.json` with the current state of every site, and
   regenerates `docs/index.html` — a simple status table — from it
6. Commits the updated snapshots/status/dashboard back to the repo and
   deploys the dashboard to GitHub Pages

## One-time setup

### 1. Push this repo to GitHub

```bash
cd website-watcher
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/website-watcher.git
git push -u origin main
```

### 2. Gmail App Password

- Enable 2-Step Verification on the sending Gmail account (matt@buildwithlogic.com)
- Go to https://myaccount.google.com/apppasswords and create one named "Website Watcher"
- Copy the 16-character password

### 3. Add repo secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | `matt@buildwithlogic.com` |
| `SMTP_PASSWORD` | *(the app password)* |
| `ALERT_EMAIL` | `mford05@nyit.edu` |

### 4. Enable GitHub Pages

Settings → Pages → Build and deployment → Source → **GitHub Actions**
(not "Deploy from a branch" — the workflow handles deployment itself).

### 5. First run

Actions tab → "Website Change Detector" → Run workflow. The first run per
site just saves a baseline snapshot — no email sent for that one. After
that, every run compares against the saved snapshot and emails only on
real changes.

Your dashboard will be live at:
`https://<your-username>.github.io/website-watcher/`

## Adding more sites to monitor

Edit `websites.json`. Two modes are supported:

**`full_text`** — hashes the entire visible page text. Simplest option,
good for small/simple pages.

```json
{
  "id": "some-unique-id",
  "name": "Display name for emails/dashboard",
  "url": "https://example.gov/page",
  "notes": "Optional context shown in the dashboard",
  "mode": "full_text"
}
```

**`anchored_text`** — extracts only the text between two marker strings
that appear as their own line on the page (skips nav/header/footer noise).
Use this for larger pages where you only care about one section.

```json
{
  "id": "some-unique-id",
  "name": "Display name",
  "url": "https://example.gov/page",
  "notes": "Optional context",
  "mode": "anchored_text",
  "start_marker": "Exact heading text",
  "end_marker": "Exact text that starts the next unrelated section"
}
```

Rules for `id`: unique, lowercase letters/numbers/hyphens only — it's used
as the snapshot filename.

If a marker isn't found on a run (e.g. the site redesigned its page), the
script logs a `WARNING` in the Action's log and falls back to the full
page text rather than failing silently — worth checking the run log after
adding a new anchored-text site to confirm your markers actually matched.

## Changing the schedule

Edit the `cron` line in `.github/workflows/check.yml` (GitHub Actions cron
is always UTC):

| Goal | Cron |
|---|---|
| Daily, 9 AM Eastern | `0 13 * * *` |
| Twice daily (9 AM + 5 PM ET) | `0 13,21 * * *` |
| Weekdays only, 9 AM ET | `0 13 * * 1-5` |

## Files

- `websites.json` — list of monitored sites and their settings
- `check_websites.py` — fetches, diffs, emails, writes `status.json`
- `generate_dashboard.py` — renders `status.json` → `docs/index.html`
- `snapshots/` — last-known content + hash per site (auto-committed)
- `status.json` — current status of every site (auto-committed)
- `docs/index.html` — the dashboard GitHub Pages serves
- `.github/workflows/check.yml` — the daily automation
