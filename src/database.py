"""
SQLite database layer for the job application queue.
Uses SQLAlchemy ORM for clean model definitions.
"""

from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from contextlib import contextmanager

from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------------
# DB path — resolves relative to project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "jobs.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Session:
    return SessionLocal()


@contextmanager
def session_scope():
    """Context manager that auto-closes and auto-rollbacks on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    NEW = "new"             # Just discovered, not yet reviewed
    REVIEWED = "reviewed"   # User has seen it, ready to apply
    APPLYING = "applying"   # Auto-fill in progress
    APPLIED = "applied"     # Application submitted
    SKIPPED = "skipped"     # User dismissed
    FAILED = "failed"       # Apply attempt failed


class Portal(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    COMPANY_DIRECT = "company_direct"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    career_page = Column(String)
    linkedin_slug = Column(String)
    greenhouse_id = Column(String)
    lever_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company name={self.name!r}>"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Job metadata
    title = Column(String, nullable=False)
    location = Column(String)
    description = Column(Text)
    job_url = Column(String, unique=True, nullable=False)
    portal = Column(String, nullable=False, index=True)          # Portal enum value
    external_job_id = Column(String)                 # ID on the portal (e.g. LinkedIn job ID)

    # Status tracking
    status = Column(String, default=JobStatus.NEW, index=True)
    discovered_by = Column(String, nullable=True, index=True)  # username who triggered scan
    discovered_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewed_at = Column(DateTime)
    applied_at = Column(DateTime)
    notes = Column(Text)

    # AI-generated content (populated before applying)
    cover_letter = Column(Text)
    screening_answers = Column(Text)   # JSON blob

    company = relationship("Company", back_populates="jobs")
    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Job title={self.title!r} company={self.company.name!r} status={self.status!r}>"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    portal = Column(String, nullable=False)
    submitted_at = Column(DateTime)
    success = Column(Boolean, default=False)
    error_message = Column(Text)
    screenshot_path = Column(String)   # path to confirmation screenshot

    job = relationship("Job", back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application job_id={self.job_id} success={self.success}>"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist.
    SQLAlchemy's create_all() uses checkfirst=True semantics by default —
    it issues a CREATE TABLE IF NOT EXISTS equivalent per dialect, so calling
    this multiple times is safe and idempotent.
    """
    Base.metadata.create_all(bind=engine)  # checkfirst=True is the default


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def upsert_job(session: Session, job_data: dict) -> tuple[Job, bool]:
    """
    Insert a job if job_url is new; skip if already exists.
    Handles concurrent inserts gracefully (UNIQUE constraint race condition).
    Returns (job, created_new).
    """
    existing = session.query(Job).filter_by(job_url=job_data["job_url"]).first()
    if existing:
        return existing, False

    try:
        job = Job(**job_data)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job, True
    except Exception:
        session.rollback()
        # Another thread inserted the same URL — fetch and return it
        existing = session.query(Job).filter_by(job_url=job_data["job_url"]).first()
        if existing:
            return existing, False
        raise


def get_jobs_by_status(session: Session, status: JobStatus) -> list[Job]:
    return (
        session.query(Job)
        .filter(Job.status == status)
        .order_by(Job.discovered_at.desc())
        .all()
    )


def mark_job(session: Session, job_id: int, status: JobStatus, **kwargs) -> None:
    job = session.get(Job, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    job.status = status
    for k, v in kwargs.items():
        setattr(job, k, v)
    session.commit()
