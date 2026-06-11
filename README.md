# JobBot — AI-Powered Job Application Engine

Self-hosted job search automation. JobBot scans 9 portals, scores jobs against your profile, generates cover letters, and submits applications — while you sleep.

**No subscriptions. No third-party data. Everything runs on your machine.**

---

## Features at a Glance

### Core Features (No AI Key Required)

| Feature | Description |
|---|---|
| **Multi-Portal Discovery** | Scans 9 job portals on demand |
| **Smart Inbox** | Jobs arrive filtered, sorted, and ready to review |
| **Auto Apply** | Fills and submits application forms hands-free on 5 portals |
| **Rich Profile** | Stores personal info, work experience, skills, education, preferences |
| **Keyword Filters** | Include/exclude keywords, target locations — all configurable from the dashboard |
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
| Portal | Type |
|---|---|
| **LinkedIn** | HTTP — LinkedIn Easy Apply |
| **Naukri** | Browser — full form-fill |
| **Glassdoor** | Browser — full form-fill |
| **Greenhouse** | HTTP — ATS form-fill |
| **Lever** | HTTP — ATS form-fill |

### Discovery Only (4 portals)
| Portal | Type |
|---|---|
| **Indeed** | HTTP |
| **Monster** | HTTP |
| **HiringCafe** | Browser |
| **Instahire** | Browser |
| **Uplers** | HTTP |

---

## Quick Start

### Requirements
- Python 3.11+

### Windows — One Click

Double-click **`setup.bat`**. It installs all dependencies, installs the Playwright browser, and launches the dashboard automatically. Nothing else to do.

### Mac / Linux

```bash
git clone https://github.com/yourname/jobbot
cd jobbot
bash scripts/setup.sh
python main.py dashboard
```

Open **http://localhost:8000**. First user to sign up becomes admin.

---

## Configure

No manual config editing needed. From the dashboard, open the ⚙ **Config** panel to set keywords, locations, exclude filters, and toggle portals on/off — all saved automatically.

`config/config.yaml` is the backing file and ships with sensible defaults. You only need to edit it directly if you want to pre-configure before first launch.

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

Click the **Profile** icon in the navbar:
- Fill Personal Info, Professional details, Skills, Education, Work Experience
- **With AI:** Upload resume (PDF/DOCX) → AI fills everything automatically

### 2. Run a Discovery Scan

Click **⚡ Scan** in the navbar. The live feed shows every portal hit, job found, and new job count in real time. Scan runs in the background — close the feed panel and it keeps going.

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
| `JOBBOT_ADMIN_USER` | `admin` | Admin username created on first run |
| `JOBBOT_ADMIN_PASS` | `adminadmin` | Admin password — **change this** |
| `JOBBOT_HEADED` | _(unset)_ | Set to `1` to run browser portals in visible mode (useful for debugging) |

Host and port are CLI options, not env vars:
```bash
python main.py dashboard --host 127.0.0.1 --port 8000
```

### Database

SQLite at `data/jobs.db`.

```bash
# Delete all jobs (keep users and settings) — Linux/Mac
sqlite3 data/jobs.db "DELETE FROM jobs;"

# Delete all jobs — Windows
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); c.execute('DELETE FROM jobs'); c.commit()"

# Full reset (deletes everything)
# Linux/Mac:  rm data/jobs.db
# Windows:    del data\jobs.db
```

---

## Project Structure

```
jobbot/
├── main.py                    # CLI entry point (dashboard / discover / status)
├── setup.bat                  # Windows one-click setup + launch
├── scripts/
│   └── setup.sh               # Mac/Linux setup script
├── requirements.txt
├── config/
│   ├── config.yaml            # Portal toggles and keyword filters (editable from dashboard)
│   ├── profile.example.yaml   # Profile template — copy to profile.yaml and fill in
│   └── credentials.yaml       # Portal login credentials (gitignored)
├── src/
│   ├── api.py                 # All FastAPI routes
│   ├── auth.py                # JWT, bcrypt, user management
│   ├── auth_routes.py         # /auth/* endpoints
│   ├── background.py          # Scan thread lifecycle
│   ├── runner.py              # Discovery orchestration (9 portals)
│   ├── apply.py               # Auto-apply orchestration
│   ├── database.py            # SQLAlchemy models (Job, User, UserSettings)
│   ├── utils.py               # Config and profile helpers
│   ├── ai_search.py           # Semantic search
│   ├── ai/
│   │   ├── service.py         # Groq/Gemini client wrapper
│   │   └── generator.py       # Cover letter, scoring, skill gap, interview prep
│   ├── discovery/             # One file per portal (9 portals)
│   └── autofill/
│       ├── profile_adapter.py # Normalises DB/YAML profile for form-fill
│       ├── runner.py          # Playwright browser coordinator
│       └── *.py               # Per-portal form-fill handlers (5 portals)
└── dashboard/
    ├── index.html             # Main dashboard (React 18 via CDN, no build step)
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
