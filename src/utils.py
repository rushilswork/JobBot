"""Shared utilities: config loading, logging."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jobbot")
for _lib in ("asyncio","urllib3","aiohttp","playwright","websockets"):
    logging.getLogger(_lib).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def load_config() -> dict:
    path = PROJECT_ROOT / "config" / "config.yaml"
    if not path.exists():
        log.warning("config/config.yaml not found — returning empty config")
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"Failed to load config.yaml: {e}")
        return {}


def load_profile() -> dict:
    path = PROJECT_ROOT / "config" / "profile.yaml"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"Failed to load profile.yaml: {e}")
        return {}


def load_credentials() -> dict:
    path = PROJECT_ROOT / "config" / "credentials.yaml"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"Failed to load credentials.yaml: {e}")
        return {}
