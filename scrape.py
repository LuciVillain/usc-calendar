"""
USC -> .ics scraper for BEAT81 Fhain Ride + Boxi Circuit.
Runs in GitHub Actions daily. Outputs usc.ics in the repo root.
"""

import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
VENUES = [
    {"id": 10831, "label": "Fhain Ride",    "emoji": "🚴"},
    {"id": 24862, "label": "Boxi Circuit",  "emoji": "🥊"},
]
CITY = 1                    # 1 = Berlin
DAYS_AHEAD = 14
SERVICE_TYPES = [0, 1]      # USC splits classes across two service_type values; fetch both
OUTPUT_ICS = Path("usc.ics")
DEBUG_DIR = Path("debug")   # raw HTML dumps for troubleshooting
TIMEZONE = "Europe/Berlin"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# ----------------------------


def fetch_day(venue_id: int, date: str, service_type: int) -> str:
    """Hit the USC activities endpoint, return the HTML blob from data.content."""
    url = "https://urbansportsclub.com/en/activities"
    params = {
        "service_type": service_type,
        "address_id":   venue_id,
        "city":         CITY,
        "date":         date,
    }
    headers = {
        "User-Agent":       USER_AGENT,
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    cookies = {"city": str(CITY)}
    r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=20)
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", {}).get("content", "") or ""


def parse_classes(html: str, date: str, venue_label: str) -> list[dict]:
    """
    Extract class entries from the HTML blob.
    Returns: list of {start: datetime, end: datetime, title: str, coach: str, raw: str}
    Defensive: tries multiple selectors. If structure changes, returns [] and dumps HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    classes = []

    # Each class is rendered as a div with class containing "smm-class-snippet"
    snippets = soup.select('div[class*="smm-class-snippet"]')

    for snip in snippets:
        text = snip.get_text(" ", strip=True)

        # Time pattern: "HH:MM" or "HH:MM - HH:MM"
        time_match = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", text)
        if time_match:
            start_str, end_str = time_match.group(1), time_match.group(2)
        else:
            single = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            if not single:
                continue
            start_str = single.group(1)
            end_str = None

        # Try to pull a class title: look for known title selectors first, fall back to heuristics
        title = ""
        for sel in ["h3", "h4", ".class-title", ".activity-title", ".title", "strong"]:
            el = snip.select_one(sel)
            if el and el.get_text(strip=True):
                title = el.get_text(strip=True)
                break
        if not title:
            # Strip the time out of the full text and grab the first chunk
            cleaned = re.sub(r"\d{1,2}:\d{2}\s*[-–]?\s*\d{0,2}:?\d{0,2}", "", text).strip()
            title = cleaned.split("  ")[0][:60] if cleaned else "Class"

        # Coach: heuristic, often appears after "with" or in a specific element
        coach = ""
        coach_match = re.search(r"\b(?:with|mit|coach)\s+([A-Z][\w\.\-]+(?:\s+[A-Z][\w\.\-]+)?)", text)
        if coach_match:
            coach = coach_match.group(1)

        # Build datetimes
        try:
            start_dt = datetime.strptime(f"{date} {start_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if end_str:
            try:
                end_dt = datetime.strptime(f"{date} {end_str}", "%Y-%m-%d %H:%M")
                if end_dt <= start_dt:  # crossed midnight, unlikely but safe
                    end_dt += timedelta(days=1)
            except ValueError:
                end_dt = start_dt + timedelta(minutes=45)
        else:
            end_dt = start_dt + timedelta(minutes=45)

        classes.append({
            "start": start_dt,
            "end":   end_dt,
            "title": title,
            "coach": coach,
            "venue": venue_label,
        })

    return classes


def make_uid(c: dict) -> str:
    """Stable UID so re-runs update events instead of duplicating."""
    key = f"{c['venue']}|{c['start'].isoformat()}|{c['title']}"
    return hashlib.md5(key.encode()).hexdigest() + "@usc-calendar"


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def to_ics(events: list[dict]) -> str:
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LuciVillain//USC Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:USC Classes",
        f"X-WR-TIMEZONE:{TIMEZONE}",
    ]
    for c in events:
        # Find venue emoji
        emoji = next((v["emoji"] for v in VENUES if v["label"] == c["venue"]), "")
        summary = f"{emoji} {c['venue']} — {c['title']}".strip()
        if c["coach"]:
            summary += f" ({c['coach']})"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{make_uid(c)}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;TZID={TIMEZONE}:{c['start'].strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={TIMEZONE}:{c['end'].strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{ics_escape(summary)}",
            f"LOCATION:{ics_escape(c['venue'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    DEBUG_DIR.mkdir(exist_ok=True)
    all_events: list[dict] = []
    seen_keys: set[str] = set()  # dedupe across service_types

    today = datetime.now().date()
    for offset in range(DAYS_AHEAD):
        date = (today + timedelta(days=offset)).isoformat()
        for venue in VENUES:
            for st in SERVICE_TYPES:
                try:
                    html = fetch_day(venue["id"], date, st)
                except Exception as e:
                    print(f"[WARN] fetch failed venue={venue['label']} date={date} st={st}: {e}", file=sys.stderr)
                    continue

                # Dump raw HTML on the very first non-empty response (for debugging)
                if html and not (DEBUG_DIR / "sample.html").exists():
                    (DEBUG_DIR / "sample.html").write_text(html, encoding="utf-8")
                    print(f"[INFO] saved debug/sample.html ({len(html)} bytes)")

                events = parse_classes(html, date, venue["label"])
                for e in events:
                    key = f"{e['venue']}|{e['start'].isoformat()}|{e['title']}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    all_events.append(e)
                print(f"  {venue['label']} {date} st={st}: {len(events)} classes")

    print(f"\nTotal unique events: {len(all_events)}")
    if not all_events:
        print("[ERROR] zero events parsed — check debug/sample.html", file=sys.stderr)
        # Still write an empty (but valid) calendar so subscribers don't break
    OUTPUT_ICS.write_text(to_ics(all_events), encoding="utf-8")
    print(f"Wrote {OUTPUT_ICS}")


if __name__ == "__main__":
    main()
