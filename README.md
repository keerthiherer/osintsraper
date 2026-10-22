# MindSmiths Lead Intelligence

A local lead-research dashboard for finding businesses that need a better website.
It discovers local businesses, checks whether their website exists or works, collects
publicly available contact and social details, scores each lead, and exports the result
to CSV or Excel.

Built for MindSmiths (backed by Melouz Technologies Pvt Ltd). Everything runs on your
machine: SQLite for storage and Streamlit for the dashboard.

## Quick start (Windows)

1. Double-click `run.bat`.
2. The first run creates `.venv`, installs dependencies, copies `.env.example` to `.env`
   and opens the dashboard at <http://localhost:8501>.
3. Choose **OpenStreetMap** (free, no key) or **Demo mode** and run a search.

Manual start:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m streamlit run app.py
```

Requires Python 3.10+ (3.11 recommended).

## What it does

- **Discover** businesses by city, locality, category or keywords.
- **Check websites** for missing, broken, parked or thin pages.
- **Enrich** public phone numbers, emails, Instagram, Facebook and LinkedIn profiles.
- **Score** leads from 0 to 100 with transparent, configurable rules.
- **Prioritise** businesses with no website first, then unreachable websites.
- **Persist** every lead in SQLite with deduplication and conservative merging.
- **Export** filtered leads to CSV or Excel, including the source of each contact field.

## Data sources

| Provider | Key required | What it provides | Notes |
| --- | --- | --- | --- |
| **OpenStreetMap** | No | Business names, addresses, some phones, websites and social tags | Free public Overpass API. Falls back to Nominatim (partial results) when Overpass is unavailable. No Google ratings or reviews. |
| **SerpAPI Google Maps** | `SERPAPI_KEY` | Richer listings, ratings, review counts, phones and websites | Optional paid service with a free tier. Get a key at <https://serpapi.com>. |
| **Demo mode** | No | 16 fictional leads from `data/sample_leads.csv` | For testing the UI without network calls. Demo records are not real businesses. |

### Web-presence search

For businesses without a website, the app searches public web results for social
profiles, phones and emails. It uses DuckDuckGo's public HTML endpoint and falls back to
a public page reader when the endpoint rate-limits the local IP. When `SERPAPI_KEY` is
set, SerpAPI's Google engine is used automatically.

- Only public business data is collected.
- No logins, CAPTCHA solving, private profiles or access-control bypasses.
- Social matches are scored by name/location confidence.
- Follower counts from search snippets are marked **unverified** and displayed as
  `~N (Needs manual verification)`. They do not add score points until verified.
- Activity dates are only used when verified.
- Public search is rate-limited and can occasionally return no results. Use a
  `SERPAPI_KEY` for more reliable coverage, or retry later.

## Lead scoring

Default rules (all configurable in the sidebar):

| Signal | Points |
| --- | --- |
| No website listed | +30 |
| Website unreachable | +20 |
| Verified social followers >= threshold | +15 |
| Recent verified social activity | +10 |
| Public phone available | +5 |
| Public email available | +5 |
| Rating >= 4.0 with >= 20 reviews | +10 |
| Strong social match | +5 |

Scores are clamped to 100. **High priority** is 80+, **Medium** is 60–79, otherwise
**Low priority**. A missing website is weighted heavily because those businesses are the
best fit for a website-development offer.

## Daily workflow

1. Run a search for a city and category.
2. Open the **Leads** table; no-website businesses appear first.
3. Review a lead, verify its social/contact details, then mark it **Reviewed** or
   **Contacted** and add notes.
4. Exclude poor matches so they do not clutter future views.
5. Export the filtered list to CSV/Excel for outreach.

Use **Re-enrich stored leads** to refresh website checks and contacts for saved leads.
Use **Recalculate scores** after changing scoring rules.

## Configuration

Copy `.env.example` to `.env` and edit as needed:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SERPAPI_KEY` | empty | Enables SerpAPI Google Maps discovery and Google web search |
| `DB_PATH` | `data/mindsmiths.db` | SQLite database path |
| `LOG_PATH` | `logs/mindsmiths.log` | Log file path |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout in seconds |
| `REQUEST_DELAY` | `1.0` | Delay between website requests |
| `MAX_WORKERS` | `4` | Parallel enrichment workers (1–8) |
| `OVERPASS_URL` | `https://overpass-api.de/api/interpreter` | Overpass endpoint |
| `DEFAULT_CITY` | `Chennai` | Default search city |
| `DEFAULT_MIN_FOLLOWERS` | `2000` | Default follower scoring threshold |
| `DEFAULT_ACTIVE_DAYS` | `30` | Default recent-activity window |
| `WEB_SEARCH_ENABLED` | `true` | Enable public web-presence search |
| `WEB_SEARCH_DELAY` | `1.2` | Minimum delay between public searches |
| `WEB_SEARCH_RESULTS` | `10` | Results per public search (3–20) |
| `WEB_SEARCH_ENGINE` | `auto` | `auto`, `duckduckgo` or `serpapi` |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers scoring, deduplication, website checks, social/contact extraction,
export, discovery validation and web-presence matching. Tests use mocked pages and local
HTTP servers; they do not depend on live third-party services.

## Project layout

```
app.py                  Streamlit dashboard
config.py               Settings and scoring defaults
mindsmiths/
  discovery.py          OpenStreetMap, Nominatim fallback, SerpAPI, demo providers
  website.py            Website checks and page fetching
  contacts.py           Email/phone/contact-form extraction
  social.py             Social-link and JSON-LD extraction
  presence.py           Public web-presence search and matching
  enrichment.py         Website + contact + social orchestration
  scoring.py            Transparent 0–100 lead scoring
  db.py                 SQLite schema, deduplication and persistence
  pipeline.py           Search, re-enrichment and rescoring flows
  export.py             CSV/Excel export
  models.py             Business and social-profile models
data/sample_leads.csv   16 fictional demo leads
tests/                  Offline test suite
logs/                   Application log
run.bat                 One-click Windows launcher
```

## Coverage and limitations

- OpenStreetMap coverage varies by city; many businesses are not mapped.
- OpenStreetMap does not provide Google ratings, review counts or Google Maps place URLs.
- SerpAPI's free tier has a monthly request limit.
- Businesses without a website often have no public email. A missing email is common and
  does not mean enrichment failed.
- Public search engines rate-limit automated traffic. The app applies delays and
  fallbacks, but temporary gaps are possible.
- Social profiles can share a name with another business. Every match shows a confidence
  value and should be verified before outreach.
- Follower counts and activity are intentionally conservative. Unverified values never
  increase a lead's score.
- This tool is for public business research. Respect website terms, applicable privacy
  laws (including India's DPDP Act), and anti-spam rules. Do not use it for mass
  unsolicited messaging.

## Troubleshooting

**Overpass is slow or unavailable.** The app automatically tries Nominatim, which may
return fewer results. Retry later, set a different `OVERPASS_URL`, or use SerpAPI/demo
mode.

**No social profiles or emails found.** Public search may be rate-limited, or the
business may not publish those details. Add a `SERPAPI_KEY` for better coverage, retry
after a pause, or verify manually.

**Dashboard does not open.** Confirm the virtual environment is active and run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Check `logs/mindsmiths.log` for details.
