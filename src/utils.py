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
# Silence noisy third-party debug logs
for _lib in ("asyncio","urllib3","aiohttp","playwright","websockets"):
    logging.getLogger(_lib).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def load_config() -> dict:
    path = PROJECT_ROOT / "config" / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_profile() -> dict:
    path = PROJECT_ROOT / "config" / "profile.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_credentials() -> dict:
    path = PROJECT_ROOT / "config" / "credentials.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}
