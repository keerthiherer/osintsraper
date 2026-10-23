# MindSmiths Sales Intelligence Platform

A local, evidence-based sales workspace for MindSmiths (backed by Melouz Technologies
Pvt Ltd). It discovers businesses that may need a better website, scores the opportunity,
audits the current site, builds scope-based quotations, tracks leads in a CRM, drafts
outreach, and finds public freelance web-development opportunities.

Everything runs on your machine: SQLite for storage and Streamlit for the dashboard. No
paid API is required for the default workflow. The platform never invents revenue,
followers, clients, budgets or contact details, and it never sends messages or submits
bids automatically.

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

## The seven tabs

1. **Business Discovery** — discover and filter businesses, inspect contacts and socials,
   mark qualified/contacted, exclude poor matches, and export CSV/Excel.
2. **Lead Intelligence** — record public evidence, see revenue category and conservative
   business-size/budget-fit bands, review the website-need score, recommended offer,
   likely objections and next action.
3. **Website Audit** — run a lightweight homepage/contact-page audit with findings,
   limitations and service suggestions.
4. **Quotation Assistant** — configure scope, get a catalogue-based INR range, save the
   proposal to the CRM, and download a print-ready HTML or PDF quotation.
5. **Freelance Opportunities** — search public Freelancer.com, Remotive and Arbeitnow
   listings, score matches, filter budgets/recency/status, and export the results.
6. **Sales CRM** — pipeline status, follow-ups, budgets, quoted/won values, activity
   history, reply/conversion metrics and CRM exports.
7. **Settings and Data Sources** — configure opportunity/freelance weights and the pricing
   catalogue, review source availability, back up the database, retry failed website
   checks, merge duplicates and draft outreach.

## Data sources

| Provider | Key required | What it provides | Notes |
| --- | --- | --- | --- |
| **OpenStreetMap** | No | Business names, addresses, some phones, websites and social tags | Free public Overpass API. Falls back to Nominatim when Overpass is unavailable. No Google ratings or reviews. |
| **SerpAPI Google Maps** | `SERPAPI_KEY` | Richer listings, ratings, review counts, phones and websites | Optional paid service with a free tier. Get a key at <https://serpapi.com>. |
| **Demo mode** | No | 16 fictional leads from `data/sample_leads.csv` | For testing the UI without network calls. Demo records are not real businesses. |
| **Freelancer.com API** | No | Active public projects, budgets, skills, bid counts | Public endpoint. Respect Freelancer's terms and rate limits. |
| **Remotive API** | No | Public remote jobs | Jobs, not freelance projects. Open status can change. |
| **Arbeitnow API** | No | Public job-board listings | Jobs, not freelance projects. Search is applied locally. |
| **Upwork API** | `UPWORK_ACCESS_TOKEN` | Upwork job search | Requires OAuth. The connector is experimental; verify the current schema. No unauthenticated scraping. |
| **PeoplePerHour / Guru** | N/A | Manual use only | No documented public API; the app does not scrape them. |

### Web-presence search

For businesses without a website, the app searches public index results for social
profiles, phones and emails. It uses DuckDuckGo's public HTML endpoint and falls back to
a public page reader when the endpoint rate-limits the local IP. When `SERPAPI_KEY` is
set, SerpAPI's Google engine is used automatically.

- Only public business data is collected.
- No logins, CAPTCHA solving, private profiles or access-control bypasses.
- Social matches are scored by name/location confidence.
- Follower counts from search snippets are marked **unverified** and displayed as
  `~N (Needs manual verification)`. They do not add score points until verified.
- Public search is rate-limited and can occasionally return no results. Use a
  `SERPAPI_KEY` for more reliable coverage, or retry later.

## How scoring works

### Legacy lead score (0–100)

Default rules (configurable in the sidebar): no website +30, unreachable website +20,
verified followers +15, recent verified activity +10, public phone +5, public email +5,
strong rating/reviews +10, strong social match +5. High priority is 80+, medium 60–79.

### Website opportunity score (0–100)

Separate from the lead score, this estimates the strength of the business's **need** for a
better website, not its intent to buy. Default weights (editable in Settings): no website
+20, website problems +15, recent verified activity +10, verified audience +10, multiple
locations/substantial catalogue +10, promotes services/bookings +10, public contact +5,
established operations +10, expansion +10.

Each signal is labelled `positive`, `known` or `unknown`. Missing evidence stays unknown
and does not score. The result includes confidence, likely objections, a recommended offer
and a next action. Classification: high-priority (75+ with non-low confidence), potential
(50+), needs more research, or low-priority (below 30 with non-low confidence).

### Revenue intelligence

Revenue is never estimated by multiplying reviews or followers. The app separates:

1. **Verified revenue disclosed publicly** — only when you enter a figure and source.
2. **Third-party estimate** — only when you enter a figure and cited source; shown as an
   estimate, not fact.
3. **Broad business-size category only** — inferred from public locations, catalogue size,
   price range, review volume, services and booking signals. It is not a revenue figure.
4. **Insufficient evidence** — no defensible estimate; quotations are scope-based.

## Quotations

Quotations use a configurable INR catalogue (`data/pricing_catalogue.json`), not revenue
guesses. Choose website type, pages, features, maintenance, hosting/domain, integrations
and support hours. The result includes a price range, delivery estimate, effort, line
items, assumptions, exclusions and payment milestones. Downloads are available as:

- a branded, print-ready HTML document;
- a branded PDF generated with ReportLab.

Business-size evidence may inform the suggested package but never automatically inflates
the price.

## Daily workflow

1. Run a search for a city and category.
2. Open **Lead Intelligence**, record sourced public evidence, and identify high-priority
   opportunities.
3. Audit the website when one exists.
4. Build and save a scope-based quotation; mark it sent when appropriate.
5. Use the **Sales CRM** for follow-ups, objections, activity notes and pipeline metrics.
6. Draft evidence-based outreach in **Settings and Data Sources**; copy it and send it
   yourself.
7. Export filtered leads or CRM records to CSV/Excel.

Use **Re-enrich stored leads** to refresh website checks and contacts. Use **Recalculate
all scores** after changing weights.

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
| `WEB_SEARCH_ENABLED` | `true` | Enable public web-presence search |
| `WEB_SEARCH_DELAY` | `1.2` | Minimum delay between public searches |
| `WEB_SEARCH_RESULTS` | `10` | Results per public search (3–20) |
| `WEB_SEARCH_ENGINE` | `auto` | `auto`, `duckduckgo` or `serpapi` |
| `FREELANCER_API_URL` | Freelancer active-projects endpoint | Override the public API URL |
| `REMOTIVE_API_URL` | Remotive API | Override the public API URL |
| `ARBEITNOW_API_URL` | Arbeitnow API | Override the public API URL |
| `UPWORK_ACCESS_TOKEN` | empty | Enables the Upwork GraphQL connector |
| `UPWORK_GRAPHQL_URL` | `https://api.upwork.com/graphql` | Upwork GraphQL endpoint |
| `FREELANCE_FETCH_DETAILS` | `false` | Reserved for fetching extra listing details |
| `COMPANY_CONTACT` | `sales@mindsmiths.example` | Quotation contact line |
| `COMPANY_WEBSITE` | `https://mindsmiths.example` | Quotation website line |

Rule and catalogue files are created in `data/` when you save settings:

- `data/opportunity_rules.json`
- `data/freelance_rules.json`
- `data/pricing_catalogue.json`

## Backup and database safety

The database is migrated automatically when new columns/tables are needed. Existing data
is preserved. Use **Back up database now** in the sidebar (or **Back up database** in
Settings) to create a timestamped copy in `data/`.

A pre-upgrade backup is kept at `data/mindsmiths.db.bak_20261023_085655` for this
installation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers scoring, deduplication, website checks, social/contact extraction,
export, discovery validation, web-presence matching, revenue/opportunity logic,
quotations, audits, outreach, CRM persistence and freelance scoring/deduplication. Tests
use mocked pages and local HTTP servers; they do not depend on live third-party services.

## Project layout

```
app.py                  Streamlit dashboard (7 tabs)
config.py               Settings, scoring rules and JSON rule persistence
mindsmiths/
  discovery.py          OpenStreetMap, Nominatim fallback, SerpAPI, demo providers
  website.py            Website checks and page fetching
  contacts.py           Email/phone/contact-form extraction
  social.py             Social-link and JSON-LD extraction
  presence.py           Public web-presence search and matching
  enrichment.py         Website + contact + social orchestration
  scoring.py            Transparent 0–100 lead scoring
  revenue.py            Revenue categories and business-size bands
  opportunity.py        Website-need scoring and sales guidance
  audit.py              Lightweight evidence-based website audit
  pricing.py            Configurable INR pricing catalogue
  quotation.py          Scope-based quotes, HTML and PDF generation
  outreach.py           Evidence-based message drafts (never auto-sent)
  db.py                 SQLite schema, migrations, CRM, evidence, freelance storage
  pipeline.py           Search, re-enrichment, evidence and intelligence flows
  export.py             Lead/CRM and freelance CSV/Excel export
  models.py             Business and social-profile models
  freelance/            Public provider connectors, scoring and search service
data/sample_leads.csv   16 fictional demo leads
tests/                  Offline test suite
logs/                   Application log
run.bat                 One-click Windows launcher
```

## Coverage and limitations

- OpenStreetMap coverage varies by city; many businesses are not mapped.
- OpenStreetMap does not provide Google ratings, review counts or Google Maps place URLs.
- SerpAPI's free tier has a monthly request limit.
- Businesses without a website often have no public email or phone.
- Public search engines rate-limit automated traffic. The app applies delays and
  fallbacks, but temporary gaps are possible.
- Social profiles can share a name with another business. Every match shows a confidence
  value and should be verified before outreach.
- Follower counts and activity are intentionally conservative. Unverified values never
  increase a score.
- Revenue bands are not revenue figures. Only sourced disclosures are shown as facts.
- Website audits check the homepage and at most one contact page; they are not full
  crawls, security scans or Core Web Vitals tests.
- Freelance platforms change their APIs and terms. Listings may expire or change status;
  always open the original listing before applying.
- PeoplePerHour and Guru are manual-only because no documented public API is available.
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

**PDF quotation fails.** Confirm `reportlab` is installed
(`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`). The print-ready HTML
download always works as a fallback.

**A freelance provider fails.** Public APIs can rate-limit or change. Check the provider's
documentation and the in-app provider status table; other providers continue working.

**Dashboard does not open.** Confirm the virtual environment is active and run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Check `logs/mindsmiths.log` for details.
