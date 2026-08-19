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
    # spaces) so marker matching isn't thrown off by invisible characters
    # that don't show up when eyeballing the page.
    raw_lines = full_text.replace("\xa0", " ").split("\n")
    lines = [" ".join(l.split()) for l in raw_lines if l.strip()]

    mode = site.get("mode", "full_text")
    if mode == "full_text":
        return "\n".join(lines)

    if mode == "anchored_text":
        start_marker = site["start_marker"]
        end_marker = site["end_marker"]
        try:
            start_idx = next(
                i for i, l in enumerate(lines) if start_marker in l
            )
        except StopIteration:
            print(f"WARNING [{site['id']}]: start marker not found, using full body")
            return "\n".join(lines)
        try:
            end_idx = next(
                i for i, l in enumerate(lines)
                if end_marker in l and i > start_idx
            )
        except StopIteration:
            print(f"WARNING [{site['id']}]: end marker not found, taking 60 lines")
            end_idx = min(start_idx + 60, len(lines))
        return "\n".join(lines[start_idx:end_idx])

    raise ValueError(f"Unknown mode '{mode}' for site {site['id']}")


def fetch(site: dict) -> str:
    resp = requests.get(
        site["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
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
