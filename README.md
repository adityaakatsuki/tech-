# Company Technology Usage Dashboard

A Streamlit web app that scrapes a company's website to detect the
technologies it uses (frameworks, CMS, analytics, hosting, etc.) and
extracts a company profile (contact info, headquarters, social links). All
scraped records are persisted per-user in a database and can also be
browsed through a companion REST API.

## Features

- **Scrape & detect** — crawls a homepage plus common sub-pages
  (`/contact`, `/about`, `/legal`, ...) and matches HTML/headers against a
  signature library of 30+ technologies (React, WordPress, Shopify,
  Cloudflare, Stripe, Google Analytics, etc.)
- **Company profile extraction** — emails, phones, address, logo, social
  links, and schema.org/JSON-LD structured data
- **Auth** — email/password signup & login (JWT) plus "Sign in with Google"
  (Streamlit OAuth), forgot/reset password flow
- **Dashboard UI** — KPI cards, charts, search history, per-user theming
- **REST API** — FastAPI service (`api.py`) exposing the technology dataset
  with API-key auth, filtering, and stats endpoints (see
  [API_DOCUMENTATION.md](API_DOCUMENTATION.md))

## Tech Stack

- **UI**: Streamlit, Plotly, Altair
- **Scraping**: requests, BeautifulSoup4, phonenumbers
- **API**: FastAPI, Uvicorn
- **Data**: SQLAlchemy (SQLite locally, Postgres-ready via `DATABASE_URL`)
- **Auth**: bcrypt, python-jose (JWT), Authlib/httpx (Google OAuth)

## Project Structure

```
streamlit_app.py              # Main Streamlit dashboard (UI only)
auth.py                       # Auth core: registration, login, JWT, password reset
auth_pages.py                 # Streamlit auth screens (login/signup/reset)
database.py                   # SQLAlchemy models & DB helpers
api.py                        # FastAPI REST service
migrate.py                    # CSV -> SQLite migration script
write_secrets.py              # Writes .streamlit/secrets.toml from env vars at startup
company_tech_analysis/
  app.py                      # Standalone scraper demo app
  utils/scraper.py            # Crawling + technology detection + profile extraction
```

## Setup

1. Create and activate a virtual environment (recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with at least:
   ```
   JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
   DEV_MODE=true
   ```
   Optional variables:
   | Variable | Purpose |
   |---|---|
   | `DATABASE_URL` | SQLAlchemy URL (defaults to local `sqlite:///company_tech.db`) |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Send real password-reset emails (falls back to console logging in dev) |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `STREAMLIT_COOKIE_SECRET`, `OAUTH_REDIRECT_URI` | Enable "Sign in with Google" (written into `.streamlit/secrets.toml` by `write_secrets.py`) |

## Running the Dashboard

```bash
streamlit run streamlit_app.py
```

Open the URL Streamlit prints (defaults to http://localhost:8501).

## Running the API

```bash
python api.py
```

- Docs: http://localhost:8000/docs
- Full reference: [API_DOCUMENTATION.md](API_DOCUMENTATION.md)

## Deployment

The app is set up to deploy on Railway via the `Procfile`, which runs
`write_secrets.py` (to materialize OAuth secrets from env vars) before
starting Streamlit:

```
web: python write_secrets.py && streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

## CI

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs
on every push/PR to `main`: installs dependencies, compiles all Python
files (`compileall`), and lints with `ruff`.
