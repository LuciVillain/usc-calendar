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
    {"id": 10831, "label": "Beat81-FhainRide", "emoji": "🚴"},
    {"id": 20434, "label": "Beat81-GörliRide", "emoji": "🚴"},
    {"id": 22434, "label": "Rocycle-Fhain", "emoji": "🚴"},
    {"id": 24862, "label": "Beat81-BoxiCircuit", "emoji": "💪🏼"},
    {"id": 29126, "label": "ClubAthleten-👽LAB", "emoji": "🥊"},
    {"id": 14616, "label": "ClubAthleten-🪩DOJO", "emoji": "🥊"},
    {"id": 9594, "label": "EveryDamnDay-FHain", "emoji": "🧘🏻‍♀️"},
    {"id": 23085, "label": "SHALA-XBerg", "emoji": "🧘🏻‍♀️"},
    {"id": 24486, "label": "OPEN-FHain", "emoji": "🧘🏻‍♀️"},
    {"id": 2069, "label": "YogaBarn-LBerg", "emoji": "🧘🏻‍♀️"},
    {"id": 7475, "label": "Badeschiff", "emoji": "🏊🏼"},
    ]
CITY = 1
DAYS_AHEAD = 14
SERVICE_TYPES = [0, 1]
OUTPUT_ICS = Path("usc.ics")
DEBUG_DIR = Path("debug")
TIMEZONE = "Europe/Berlin"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# ----------------------------


def fetch_day(venue_id: int, date: str, service_type: int) -> str:
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


def looks_like_real_title(s: str) -> bool:
    """Reject junk titles like '—, 17:00, Fhain Ride' or dash-only strings."""
    if not s:
        return False
    if len(re.findall(r"[A-Za-zÀ-ÿ]", s)) < 3:
        return False
    if re.fullmatch(r"[\s\-–—,.:;]+", s):
        return False
    return True


def parse_classes(html: str, date: str, venue_label: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    classes = []

    snippets = soup.select('div[class*="smm-class-snippet"]')

    for snip in snippets:
        text = snip.get_text(" ", strip=True)

        # Time extraction
        time_match = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", text)
        if time_match:
            start_str, end_str = time_match.group(1), time_match.group(2)
        else:
            single = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            if not single:
                continue
            start_str = single.group(1)
            end_str = None

        # Title — only accept candidates that pass the sanity check
        title = ""
        for sel in ["h3", "h4", ".class-title", ".activity-title", ".title", "strong", "h5"]:
            el = snip.select_one(sel)
            if el:
                candidate = el.get_text(" ", strip=True)
                if looks_like_real_title(candidate):
                    title = candidate
                    break
        # No fallback heuristic — empty title is fine, dedup handles it

        # Coach (best-effort)
        coach = ""
        m = re.search(r"\b(?:with|mit|coach)\s+([A-Z][\wÀ-ÿ\.\-]+(?:\s+[A-Z][\wÀ-ÿ\.\-]+)?)", text)
        if m:
            coach = m.group(1)

        # Datetimes
        try:
            start_dt = datetime.strptime(f"{date} {start_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if end_str:
            try:
                end_dt = datetime.strptime(f"{date} {end_str}", "%Y-%m-%d %H:%M")
                if end_dt <= start_dt:
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
    key = f"{c['venue']}|{c['start'].isoformat()}"
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
        emoji = next((v["emoji"] for v in VENUES if v["label"] == c["venue"]), "")
        title_part = c["title"] if c["title"] else "Class"
        summary = f"{emoji} {c['venue']} — {title_part}".strip()
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
    best: dict[tuple[str, str], dict] = {}

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

                if html and not (DEBUG_DIR / "sample.html").exists():
                    (DEBUG_DIR / "sample.html").write_text(html, encoding="utf-8")
                    print(f"[INFO] saved debug/sample.html ({len(html)} bytes)")

                events = parse_classes(html, date, venue["label"])
                for e in events:
                    key = (e["venue"], e["start"].isoformat())
                    existing = best.get(key)
                    if existing is None:
                        best[key] = e
                    else:
                        ex_ok = looks_like_real_title(existing["title"])
                        new_ok = looks_like_real_title(e["title"])
                        if new_ok and not ex_ok:
                            best[key] = e
                        elif new_ok and ex_ok and len(e["title"]) > len(existing["title"]):
                            best[key] = e
                        if not best[key]["coach"] and e["coach"]:
                            best[key]["coach"] = e["coach"]
                print(f"  {venue['label']} {date} st={st}: {len(events)} classes (unique so far: {len(best)})")

    all_events = sorted(best.values(), key=lambda c: c["start"])
    print(f"\nTotal unique events: {len(all_events)}")
    if not all_events:
        print("[ERROR] zero events parsed — check debug/sample.html", file=sys.stderr)
    OUTPUT_ICS.write_text(to_ics(all_events), encoding="utf-8")
    print(f"Wrote {OUTPUT_ICS}")


if __name__ == "__main__":
    main()
