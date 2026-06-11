# JobBot — AI-Powered Job Application Engine

Self-hosted job search automation. JobBot scans 9 portals, scores jobs against your profile, generates cover letters, and submits applications — while you sleep.

**No subscriptions. No third-party data. Everything runs on your machine.**

---

## Features at a Glance

### Core Features (No AI Key Required)

| Feature | Description |
|---|---|
| **Multi-Portal Discovery** | Scans 9 job portals on demand or on a schedule |
| **Smart Inbox** | Jobs arrive filtered, sorted, and ready to review |
| **Auto Apply** | Fills and submits application forms hands-free |
| **Skill-Based Filtering** | Upload resume → filter jobs by skill match |
| **Rich Profile** | Stores personal info, work experience, skills, education, preferences |
| **Keyword Filters** | Include/exclude keywords, target locations, level filters |
| **Live Activity Feed** | Real-time scan log streamed to your browser |
| **Bulk Actions** | Approve all / skip all / mark applied in one click |
| **Multi-User Support** | Admin and viewer accounts, fully isolated per user |
| **Light & Dark Mode** | System-aware theme across all pages |
| **JWT Auth** | bcrypt passwords, httpOnly cookies, rate-limited login |
| **Local SQLite Storage** | All jobs and profiles stored locally — no cloud |

### AI Features (Groq or Gemini — Both Have Free Tiers)

| Feature | Description |
|---|---|
| **Match Scoring** | 0–100 score per job: skill overlap, experience fit, role alignment |
| **Cover Letter Generation** | Tailored per-job cover letter referencing the actual job description |
| **Skill Gap Analysis** | Skills you have vs. missing, with a learning path and time estimates |
| **Interview Preparation** | Behavioral, technical, and situational questions with answer frameworks |
| **Smart Screening Answers** | AI answers portal screening questions (salary, experience, relocation) |
| **Resume Parser** | Upload PDF/DOCX → AI extracts and fills your entire profile |
| **Natural Language Search** | Search inbox with plain English: "remote Python backend, not fintech" |

---

## Supported Portals

### Discovery + Auto-Apply (5 portals)
| Portal | Notes |
|---|---|
| **LinkedIn** | Job listings + LinkedIn Easy Apply |
| **Naukri** | India's largest job board, full form-fill |
| **Glassdoor** | Company-verified listings |
| **Indeed** | Global listings, Indeed Apply |
| **HiringCafe** | Aggregator with apply support |

### Discovery Only (5 portals)
| Portal | Notes |
|---|---|
| **Monster** | Global job aggregator |
| **Greenhouse** | ATS-hosted company listings |
| **Lever** | ATS-hosted listings via public JSON API |
| **Instahire** | India-focused portal |
| **Uplers** | Remote-first India talent platform |

---

## Quick Start

### Requirements
- Python 3.11+
- Playwright for browser-based portals

### Install

```bash
git clone https://github.com/yourname/jobbot
cd jobbot
pip install -r requirements.txt
playwright install chromium
```

### Configure

Edit `config/config.yaml`:

```yaml
filters:
  keywords:
    - software engineer
    - backend engineer
    - full stack developer
  locations:
    - India
    - Remote
    - Hyderabad
  exclude_keywords:
    - intern
    - senior staff
    - data scientist

portals:
  linkedin:
    enabled: true
  naukri:
    enabled: true
  indeed:
    enabled: true
  glassdoor:
    enabled: true
  monster:
    enabled: true
  greenhouse:
    enabled: true
  lever:
    enabled: false
  hiring_cafe:
    enabled: true
  instahire:
    enabled: false
  uplers:
    enabled: false
```

### Run

```bash
python main.py
```

Open **http://localhost:8000**. First user to sign up becomes admin.

---

## Setting Up AI (Optional)

AI features are completely optional. Discovery and auto-apply work without any API key.

### Groq — 14,400 requests/day free

1. Get a free key at [console.groq.com](https://console.groq.com)
2. Dashboard → navbar ⚙ → **AI Settings**
3. Select **Groq**, paste key, pick a model
4. Click **Test connection** → ✓ Connected
5. Toggle **Enable AI** — all AI features activate

### Gemini — 1M tokens/day free

1. Get a free key at [aistudio.google.com](https://aistudio.google.com)
2. Same steps above, select **Gemini**

### Available Models

**Groq**
- `llama-3.3-70b-versatile` — Best quality, 128k context *(recommended)*
- `llama-3.1-8b-instant` — Fastest, lower latency
- `mixtral-8x7b-32768` — Balanced, 32k context
- `gemma2-9b-it` — Lightweight

**Gemini**
- `gemini-1.5-flash` — Best free tier *(recommended)*
- `gemini-1.5-pro` — Highest quality
- `gemini-2.0-flash-exp` — Latest experimental

---

## Usage Guide

### 1. Build Your Profile

**Profile** icon in navbar:
- Fill Personal Info, Professional details, Skills, Education, Work Experience
- **Shortcut:** Upload resume (PDF/DOCX) → AI fills everything automatically

### 2. Run a Discovery Scan

Click **▶ Start** in the navbar. The live feed shows every portal hit, job found, and new job count in real time. Scan runs in the background — close the feed panel and it keeps going.

### 3. Review Your Inbox

**Inbox** tab shows new jobs:
- Each card shows title, company, location, work mode, portal, and skill match
- Click a card to open the detail drawer with full JD, AI score breakdown, cover letter, skill gap, and interview prep
- **Approve** (→ Reviewed), **Skip**, or **Auto Apply** directly from the card

### 4. Auto Apply

Click **Auto Apply** on any reviewed job:
1. JobBot opens the portal in a browser
2. Fills name, contact, experience, skills, cover letter, salary
3. Attaches resume if required
4. Submits and captures a confirmation screenshot

Watch progress in the Apply modal. You can cancel before final submission.

### 5. Track Everything

| Tab | Contents |
|---|---|
| **Inbox** | New, unreviewed jobs |
| **Reviewed** | Approved jobs ready to apply |
| **Applied** | Submitted applications |
| **Skipped** | Passed jobs (can be restored) |

---

## AI Features in Detail

### Match Score
Each job gets a 0–100 score based on actual skill overlap and role fit — not just keyword counting.
- **80–100** Strong match
- **60–79** Good match
- **40–59** Partial — some gaps
- **< 40** Weak — significant mismatch

### Cover Letter
Generated per job before Auto Apply. Available on demand in the detail drawer → AI tab → Cover Letter. References the specific JD — not a template.

### Skill Gap Analysis
Detail drawer → AI tab → Skill Gap:
- Lists skills you already have (✓)
- Lists missing skills with priority and learning resources
- Estimates time to close each gap

### Interview Prep
Detail drawer → AI tab → Interview Prep:
- 5 behavioral questions (STAR format)
- 5 technical questions tailored to the role
- Questions to ask the interviewer
- Company/role-specific prep tips

### Natural Language Search
Click the search bar at the top of the dashboard (visible when AI is active):
- `"remote Python senior, not fintech"`
- `"startup with equity, series B"`
- `"product company, no bond"`

Finds relevant jobs even without exact keyword matches.

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `JOBBOT_ADMIN_USER` | `admin` | Default admin username |
| `JOBBOT_ADMIN_PASS` | `adminadmin` | Default admin password — **change on first run** |
| `JOBBOT_HOST` | `0.0.0.0` | Bind address |
| `JOBBOT_PORT` | `8000` | Port |

### Database

SQLite at `data/jobs.db`.

```bash
# Delete all jobs (keep users and settings)
sqlite3 data/jobs.db "DELETE FROM jobs; DELETE FROM companies;"

# Full reset
rm data/jobs.db
rm data/.jwt_secret   # forces new JWT secret on next start
```

---

## Project Structure

```
jobbot/
├── main.py
├── config/
│   ├── config.yaml            # Portal toggles and keyword filters
│   ├── profile.yaml           # Fallback profile (DB takes priority)
│   └── credentials.yaml       # Optional portal login credentials
├── src/
│   ├── api.py                 # All FastAPI routes
│   ├── auth.py                # JWT, bcrypt, user store
│   ├── auth_routes.py         # /auth/* endpoints
│   ├── background.py          # Scan thread lifecycle
│   ├── runner.py              # Discovery orchestration (9 portals)
│   ├── apply.py               # Auto-apply orchestration
│   ├── database.py            # SQLAlchemy models (Job, User, UserSettings)
│   ├── utils.py               # Config and profile helpers
│   ├── ai_search.py           # Semantic search (works without AI key)
│   ├── ai/
│   │   ├── service.py         # Groq/Gemini client wrapper
│   │   └── generator.py       # Cover letter, scoring, skill gap, interview prep
│   ├── discovery/             # One file per portal (9 total)
│   └── autofill/
│       ├── profile_adapter.py # Normalises DB/YAML profile for form-fill
│       ├── runner.py          # Playwright browser coordinator
│       └── *.py               # Per-portal form-fill handlers (5 portals)
└── dashboard/
    ├── index.html             # Main dashboard (React 18 via CDN, no build)
    ├── home.html              # Landing page
    ├── login.html             # Sign in
    └── signup.html            # Create account
```

---

## Security

- Passwords hashed with bcrypt (cost factor 8)
- JWT in httpOnly, SameSite=Strict cookies — not localStorage
- Login rate limiting: 5 failures → 60s lockout per IP
- AI API keys stored in local SQLite only — never transmitted
- `data/.jwt_secret` and `config/credentials.yaml` excluded from git
- No telemetry, no analytics, no external calls except to job portals and your chosen AI provider

---

## License

MIT
