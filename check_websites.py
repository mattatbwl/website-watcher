#!/usr/bin/env python3
"""
Website Change Detector

Loops over every site in websites.json, fetches it, extracts the relevant
text (either the full page or an anchored section), compares it against the
saved snapshot, and emails an alert per site that changed.

Also writes status.json (used by the GitHub Pages dashboard in docs/) with
the current state of every monitored site.
"""

import hashlib
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SNAPSHOT_DIR = Path("snapshots")
STATUS_FILE = Path("status.json")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", SMTP_USER)


def load_config() -> dict:
    with open("websites.json", "r") as f:
        return json.load(f)


def extract_text(html: str, site: dict) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    full_text = soup.get_text("\n", strip=True)
    # Normalize whitespace (collapse runs of spaces/tabs and non-breaking
    # spaces) so marker matching isn't thrown off by invisible characters.
    raw_lines = full_text.replace("\xa0", " ").split("\n")
    lines = [" ".join(l.split()) for l in raw_lines if l.strip()]

    mode = site.get("mode", "full_text")
    if mode == "full_text":
        return "\n".join(lines)

    if mode == "anchored_text":
        start_marker = site["start_marker"]
        end_marker = site["end_marker"]

        # Search across the whole page as ONE normalized string, not
        # line-by-line. Line-based matching breaks if the heading's text
        # gets split across a line boundary by nested markup (e.g. an
        # icon or hidden span sitting between words of the heading).
        joined = " ".join(lines)

        start_pos = joined.find(start_marker)
        if start_pos == -1:
            print(f"WARNING [{site['id']}]: start marker not found, using full body")
            print(f"DEBUG [{site['id']}] extracted text length: {len(joined)} chars")
            print(f"DEBUG [{site['id']}] first 800 chars of extracted text:")
            print(joined[:800])
            print(f"DEBUG [{site['id']}] last 400 chars of extracted text:")
            print(joined[-400:])
            return "\n".join(lines)

        end_pos = joined.find(end_marker, start_pos + len(start_marker))
        if end_pos == -1:
            print(f"WARNING [{site['id']}]: end marker not found, taking 1500 chars")
            end_pos = min(start_pos + 1500, len(joined))

        return joined[start_pos:end_pos].strip()

    raise ValueError(f"Unknown mode '{mode}' for site {site['id']}")


def fetch(site: dict) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(site["url"], timeout=30, headers=headers)
    resp.raise_for_status()
    print(
        f"[{site['id']}] fetched {len(resp.text)} chars, "
        f"HTTP {resp.status_code}, final URL: {resp.url}"
    )
    return extract_text(resp.text, site)


def send_email(subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())


def check_site(site: dict, now_iso: str) -> dict:
    """Returns a status dict for this site, and sends email if changed."""
    site_id = site["id"]
    snapshot_file = SNAPSHOT_DIR / f"{site_id}.txt"
    hash_file = SNAPSHOT_DIR / f"{site_id}.hash"

    status = {
        "id": site_id,
        "name": site["name"],
        "url": site["url"],
        "notes": site.get("notes", ""),
        "last_checked": now_iso,
        "last_changed": None,
        "state": "ok",
        "error": None,
    }

    # Carry forward last_changed from prior status if present
    prev_status = load_status().get(site_id)
    if prev_status:
        status["last_changed"] = prev_status.get("last_changed")

    try:
        content = fetch(site)
    except Exception as e:
        print(f"ERROR [{site_id}]: {e}", file=sys.stderr)
        status["state"] = "error"
        status["error"] = str(e)
        return status

    new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    old_hash = hash_file.read_text().strip() if hash_file.exists() else None

    if old_hash is None:
        print(f"[{site_id}] No previous snapshot -- saving baseline, no email.")
        snapshot_file.write_text(content)
        hash_file.write_text(new_hash)
        status["state"] = "baseline"
        return status

    if new_hash != old_hash:
        print(f"[{site_id}] Change detected -- sending email.")
        old_content = snapshot_file.read_text() if snapshot_file.exists() else ""
        body = (
            f"{site['name']} has changed:\n{site['url']}\n\n"
            f"--- Current content ---\n{content}\n\n"
            f"--- Previous content ---\n{old_content}\n"
        )
        send_email(f"[Website Watcher] {site['name']} updated", body)

        snapshot_file.write_text(content)
        hash_file.write_text(new_hash)
        status["state"] = "changed"
        status["last_changed"] = now_iso
    else:
        print(f"[{site_id}] No change.")
        status["state"] = "unchanged"

    return status


def load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            data = json.loads(STATUS_FILE.read_text())
            return {s["id"]: s for s in data.get("sites", [])}
        except Exception:
            return {}
    return {}


def main() -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    config = load_config()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    results = [check_site(site, now_iso) for site in config["sites"]]

    STATUS_FILE.write_text(
        json.dumps({"generated_at": now_iso, "sites": results}, indent=2)
    )


if __name__ == "__main__":
    main()
