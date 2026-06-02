# JobBot — Automated Job Discovery Pipeline

A local-first job discovery engine that searches 9 portals by keyword and surfaces relevant software engineering roles.

## Features
- 🔍 Keyword-based discovery across LinkedIn, Naukri, Indeed, Monster, Glassdoor, Greenhouse, HiringCafe, Instahire, Uplers
- ✦ AI-powered natural language search
- 📄 Resume parsing & skill matching
- 🔒 JWT authentication with bcrypt
- 📡 Real-time SSE feed
- 🌐 Pipeline tracking (New → Reviewed → Applied → Skipped)

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
python main.py dashboard
```

Visit `http://127.0.0.1:8000`

On first run, visit `/signup` to create your admin account.

## Stack
- **Backend**: FastAPI + SQLAlchemy + SQLite
- **Frontend**: React 18 (CDN) + Babel standalone
- **Scraping**: Playwright + aiohttp + BeautifulSoup
- **Auth**: bcrypt + JWT (httpOnly cookies)
