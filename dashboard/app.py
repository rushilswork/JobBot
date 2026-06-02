"""
Job Application Bot — Dashboard
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Application, Company, Job, JobStatus, get_session, init_db, mark_job
from src.background import ensure_running, get_status, trigger_now
from src.utils import load_config

st.set_page_config(page_title="JobBot", page_icon="💼", layout="wide", initial_sidebar_state="collapsed")

init_db()
config = load_config()
interval = config.get("check_interval_minutes", 60)
ensure_running(interval_minutes=interval)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.stApp{background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);min-height:100vh;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:1.5rem 2rem 2rem 2rem !important;max-width:1400px;}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:1rem 1.5rem;margin-bottom:1.5rem;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:16px;backdrop-filter:blur(20px);}
.topbar-title{font-size:1.6rem;font-weight:700;color:#fff;letter-spacing:-0.5px;}
.topbar-title span{color:#a78bfa;}
.topbar-sub{font-size:0.82rem;color:rgba(255,255,255,0.5);margin-top:2px;}
.status-pill{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:20px;font-size:0.78rem;font-weight:600;}
.status-running{background:rgba(52,211,153,0.15);color:#34d399;border:1px solid rgba(52,211,153,0.3);}
.status-idle{background:rgba(167,139,250,0.15);color:#a78bfa;border:1px solid rgba(167,139,250,0.3);}
.status-error{background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3);}
.pulse{width:8px;height:8px;border-radius:50%;display:inline-block;animation:pulse 1.5s ease-in-out infinite;}
.pulse-green{background:#34d399;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.stats-row{display:flex;gap:12px;margin-bottom:1.5rem;flex-wrap:wrap;}
.stat-card{flex:1;min-width:90px;padding:1rem 1.2rem;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:14px;text-align:center;}
.stat-num{font-size:2rem;font-weight:700;color:#fff;line-height:1;}
.stat-label{font-size:0.7rem;color:rgba(255,255,255,0.45);margin-top:4px;letter-spacing:0.5px;text-transform:uppercase;}
.stTabs [data-baseweb="tab-list"]{background:rgba(255,255,255,0.04) !important;border-radius:12px !important;padding:4px !important;border:1px solid rgba(255,255,255,0.08) !important;gap:2px !important;}
.stTabs [data-baseweb="tab"]{border-radius:8px !important;color:rgba(255,255,255,0.5) !important;font-weight:500 !important;font-size:0.85rem !important;padding:6px 16px !important;}
.stTabs [aria-selected="true"]{background:rgba(167,139,250,0.25) !important;color:#a78bfa !important;}
.stTabs [data-baseweb="tab-border"]{display:none !important;}
.stTabs [data-baseweb="tab-panel"]{padding-top:1rem !important;}
.job-card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:1.2rem 1.4rem;margin-bottom:6px;backdrop-filter:blur(10px);}
.job-title{font-size:1rem;font-weight:600;color:#fff;margin:0;}
.job-company{font-size:0.82rem;color:rgba(255,255,255,0.55);margin-top:2px;}
.badge-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}
.badge{display:inline-flex;align-items:center;gap:3px;padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:600;}
.badge-remote{background:rgba(52,211,153,0.15);color:#34d399;border:1px solid rgba(52,211,153,0.25);}
.badge-hybrid{background:rgba(251,191,36,0.15);color:#fbbf24;border:1px solid rgba(251,191,36,0.25);}
.badge-onsite{background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.25);}
.badge-unknown{background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.4);border:1px solid rgba(255,255,255,0.1);}
.badge-portal{background:rgba(99,102,241,0.15);color:#818cf8;border:1px solid rgba(99,102,241,0.25);}
.badge-new{background:rgba(6,182,212,0.15);color:#22d3ee;border:1px solid rgba(6,182,212,0.25);}
.badge-applied{background:rgba(52,211,153,0.15);color:#34d399;border:1px solid rgba(52,211,153,0.25);}
.badge-failed{background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.25);}
.stButton>button{background:rgba(167,139,250,0.15) !important;color:#a78bfa !important;border:1px solid rgba(167,139,250,0.3) !important;border-radius:8px !important;font-weight:500 !important;font-size:0.8rem !important;width:100% !important;}
.stButton>button:hover{background:rgba(167,139,250,0.3) !important;}
.btn-primary .stButton>button{background:linear-gradient(135deg,#7c3aed,#4f46e5) !important;color:#fff !important;border:none !important;}
.btn-danger .stButton>button{background:rgba(239,68,68,0.15) !important;color:#f87171 !important;border-color:rgba(239,68,68,0.3) !important;}
.stTextInput>div>div>input,.stSelectbox>div>div{background:rgba(255,255,255,0.05) !important;color:#fff !important;border:1px solid rgba(255,255,255,0.1) !important;border-radius:8px !important;}
hr{border-color:rgba(255,255,255,0.08) !important;}
.job-time{font-size:0.72rem;color:rgba(255,255,255,0.3);}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

def _time_ago(iso_str):
    if not iso_str:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_str)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60: return f"{diff}s ago"
        if diff < 3600: return f"{diff//60}m ago"
        if diff < 86400: return f"{diff//3600}h ago"
        return f"{diff//86400}d ago"
    except Exception:
        return "?"

def _mode_badge(mode):
    icons = {"remote":"🟢","hybrid":"🟡","onsite":"🔴","unknown":"⚪"}
    cls = {"remote":"badge-remote","hybrid":"badge-hybrid","onsite":"badge-onsite"}.get(mode,"badge-unknown")
    return f'<span class="badge {cls}">{icons.get(mode,"")} {mode.upper()}</span>'

def _portal_badge(portal):
    abbr = {"linkedin":"IN","naukri":"NK","glassdoor":"GD","indeed":"ID","monster":"MN",
            "hiring_cafe":"HC","instahire":"IH","greenhouse":"GH","lever":"LV"}
    return f'<span class="badge badge-portal">{abbr.get(portal,portal[:2].upper())}</span>'

def _status_badge(status):
    cls = {"new":"badge-new","applied":"badge-applied","failed":"badge-failed"}.get(status,"badge-unknown")
    labels = {"new":"NEW","reviewed":"REVIEWED","applying":"STAGING","applied":"APPLIED","skipped":"SKIPPED","failed":"FAILED"}
    return f'<span class="badge {cls}">{labels.get(status,status.upper())}</span>'

def _work_mode(job):
    if job.notes and "work_mode:" in job.notes:
        return job.notes.split("work_mode:")[-1].strip().split()[0]
    return "unknown"

# ---- Header ----
bg = get_status()
disc_status = bg.get("status","starting")
last_run = bg.get("last_run")
last_count = bg.get("last_new_count", 0)
bg_error = bg.get("error")

if disc_status == "running":
    pill = '<span class="status-pill status-running"><span class="pulse pulse-green"></span> Discovering…</span>'
elif bg_error:
    pill = '<span class="status-pill status-error">⚠ Error</span>'
else:
    pill = f'<span class="status-pill status-idle">● Idle · last {_time_ago(last_run)} · {last_count} new</span>'

st.markdown(f"""
<div class="topbar">
  <div>
    <div class="topbar-title">💼 Job<span>Bot</span></div>
    <div class="topbar-sub">Automated discovery across 9 portals · Remote → Hybrid → Onsite</div>
  </div>
  <div>{pill}</div>
</div>
""", unsafe_allow_html=True)

# ---- Stats ----
session = get_session()
all_jobs = session.query(Job).all()
cnts = {s:0 for s in ["new","reviewed","applying","applied","skipped","failed"]}
for j in all_jobs:
    if j.status in cnts: cnts[j.status] += 1

items = [("🆕",cnts["new"],"New"),("👁",cnts["reviewed"],"Reviewed"),("⚙️",cnts["applying"],"Staging"),
         ("✅",cnts["applied"],"Applied"),("⏭",cnts["skipped"],"Skipped"),("❌",cnts["failed"],"Failed"),("📋",len(all_jobs),"Total")]
html = '<div class="stats-row">'
for icon,num,label in items:
    html += f'<div class="stat-card"><div class="stat-num">{num}</div><div class="stat-label">{icon} {label}</div></div>'
html += '</div>'
st.markdown(html, unsafe_allow_html=True)

# ---- Controls ----
c1,c2,c3 = st.columns([4,1,1])
with c1:
    search = st.text_input("", placeholder="🔍  Search jobs, companies, locations…", label_visibility="collapsed")
with c2:
    mode_f = st.selectbox("", ["All Modes","🟢 Remote","🟡 Hybrid","🔴 Onsite"], label_visibility="collapsed")
with c3:
    portal_f = st.selectbox("", ["All Portals","LinkedIn","Naukri","Glassdoor","Indeed","Monster","Greenhouse","Lever","HiringCafe","Instahire"], label_visibility="collapsed")

# ---- Tabs ----
tab_labels = ["🆕 New","👁 Reviewed","⚙️ Staging","✅ Applied","⏭ Skipped","❌ Failed","📋 All"]
tab_keys   = ["new","reviewed","applying","applied","skipped","failed","all"]
tabs = st.tabs(tab_labels)

mode_map   = {"🟢 Remote":"remote","🟡 Hybrid":"hybrid","🔴 Onsite":"onsite"}
portal_map = {"LinkedIn":"linkedin","Naukri":"naukri","Glassdoor":"glassdoor","Indeed":"indeed",
              "Monster":"monster","Greenhouse":"greenhouse","Lever":"lever","HiringCafe":"hiring_cafe","Instahire":"instahire"}

for tab, key in zip(tabs, tab_keys):
    with tab:
        q = session.query(Job).join(Company)
        if key != "all": q = q.filter(Job.status == key)
        jobs = q.order_by(Job.discovered_at.desc()).all()

        if search:
            s = search.lower()
            jobs = [j for j in jobs if s in j.title.lower() or s in j.company.name.lower() or s in (j.location or "").lower()]
        if mode_f != "All Modes":
            tgt = mode_map.get(mode_f,"")
            if tgt: jobs = [j for j in jobs if _work_mode(j)==tgt]
        if portal_f != "All Portals":
            tgt = portal_map.get(portal_f,"")
            if tgt: jobs = [j for j in jobs if j.portal==tgt]

        if not jobs:
            st.markdown('<div style="text-align:center;padding:3rem;color:rgba(255,255,255,0.3);">No jobs · discovery runs automatically in the background</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:rgba(255,255,255,0.35);font-size:0.75rem;margin-bottom:8px;">{len(jobs)} job(s)</div>', unsafe_allow_html=True)
            for job in jobs:
                mode = _work_mode(job)
                disc_dt = job.discovered_at.strftime("%d %b %Y") if job.discovered_at else ""
                st.markdown(f"""
<div class="job-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <div class="job-title">{job.title}</div>
      <div class="job-company">{job.company.name} &middot; <span style="color:rgba(255,255,255,0.4)">{job.location or "—"}</span></div>
      <div class="badge-row">{_mode_badge(mode)}{_portal_badge(job.portal)}{_status_badge(job.status)}</div>
    </div>
    <div class="job-time">{disc_dt}</div>
  </div>
</div>""", unsafe_allow_html=True)

                b1,b2,b3,b4 = st.columns(4)
                uid = f"{job.id}_{key}"
                with b1:
                    if st.button("🔗 Open", key=f"view_{uid}"):
                        st.markdown(f"[Open job posting]({job.job_url})")
                with b2:
                    if job.status in ("new","failed"):
                        if st.button("👁 Approve", key=f"app_{uid}"):
                            mark_job(session, job.id, JobStatus.REVIEWED, reviewed_at=datetime.utcnow())
                            st.rerun()
                    elif job.status == "applying":
                        if st.button("✅ Mark Applied", key=f"mapp_{uid}"):
                            mark_job(session, job.id, JobStatus.APPLIED, applied_at=datetime.utcnow())
                            st.rerun()
                with b3:
                    if job.status in ("new","reviewed"):
                        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
                        if st.button("⚡ Auto-Fill", key=f"fill_{uid}"):
                            with st.spinner(f"Filling {job.title}…"):
                                try:
                                    from src.apply import prepare_and_stage
                                    ok = asyncio.run(prepare_and_stage(job.id))
                                    st.success("Staged!" if ok else "Failed — check logs")
                                except Exception as e:
                                    st.error(str(e))
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                with b4:
                    if job.status not in ("applied","skipped"):
                        st.markdown('<div class="btn-danger">', unsafe_allow_html=True)
                        if st.button("⏭ Skip", key=f"skip_{uid}"):
                            mark_job(session, job.id, JobStatus.SKIPPED)
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

                if job.description or job.cover_letter:
                    with st.expander("Details / AI content"):
                        if job.description:
                            st.markdown(job.description[:2000])
                        if job.cover_letter:
                            st.text_area("Cover letter", job.cover_letter, height=160, key=f"cl_{uid}", disabled=True)
                        for app in session.query(Application).filter_by(job_id=job.id).all():
                            if app.screenshot_path and Path(app.screenshot_path).exists():
                                st.image(app.screenshot_path, caption="Application preview")

                st.markdown('<hr style="margin:4px 0 12px 0;opacity:0.08">', unsafe_allow_html=True)

# ---- Footer ----
st.markdown("---")
fc1, fc2 = st.columns([1,4])
with fc1:
    st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
    if st.button("🔄 Run Discovery Now", use_container_width=True):
        trigger_now()
        st.toast("Discovery triggered!", icon="🔍")
    st.markdown('</div>', unsafe_allow_html=True)
with fc2:
    nxt = bg.get("next_run_in_seconds", interval*60)
    st.markdown(
        f'<div style="color:rgba(255,255,255,0.3);font-size:0.75rem;padding-top:12px;">' +
        f'Runs every {interval}m · next ~{int(nxt/60)}m · auto-refreshes every 60s</div>',
        unsafe_allow_html=True)

session.close()
time.sleep(60)
st.rerun()
