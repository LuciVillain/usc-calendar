# USC Calendar
 
Auto-generated Google Calendar feed for BEAT81 Fhain Ride + Boxi Circuit (via Urban Sports Club).
 
Live feed: `https://lucivillain.github.io/usc-calendar/usc.ics`
 
## How it works
 
- `scrape.py` hits the USC `activities` API for both venues, next 14 days
- Parses the embedded HTML schedule into events
- Writes `usc.ics`
- GitHub Actions runs this daily at ~06:00 Berlin time
- GitHub Pages serves `usc.ics` at the URL above
- Google Calendar subscribes to that URL → auto-refreshes
## To add another venue
 
Edit `scrape.py`, add to the `VENUES` list:
```python
{"id": 12345, "label": "My Studio", "emoji": "🏋️"},
```
Get the `id` by opening the venue's USC page, DevTools → Network → look for `activities?...&address_id=XXXXX`.
 
## Debugging
 
If the calendar is empty, check `debug/sample.html` in the repo — that's the raw HTML the script tried to parse. Most likely USC changed their HTML structure and selectors in `parse_classes()` need updating.
