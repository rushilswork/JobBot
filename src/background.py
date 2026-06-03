"""
Background discovery daemon.
Runs in a daemon thread started once when the dashboard boots.
Supports Start / Stop / Trigger-now controls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jobbot.bg")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE   = PROJECT_ROOT / "data" / "discovery_state.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

_lock          = threading.Lock()
_thread: threading.Thread | None = None
_stop_event    = threading.Event()      # set → loop exits after current run
_current_loop  = None                    # running asyncio loop for cancellation
_trigger_event = threading.Event()     # set → skip current sleep, run now

# Live progress log — last 60 messages, thread-safe
_progress_log:  deque = deque(maxlen=60)
_progress_lock  = threading.Lock()


# ── State helpers ─────────────────────────────────────────────────────────────

def _read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(data: dict) -> None:
    with _lock:
        existing = _read_state()
        existing.update(data)
        with open(STATE_FILE, "w") as f:
            json.dump(existing, f, indent=2)


def get_status() -> dict:
    return _read_state()


# ── Progress log ──────────────────────────────────────────────────────────────

def _add_progress(msg: str) -> None:
    entry = {"t": datetime.utcnow().strftime("%H:%M:%S"), "msg": msg}
    with _progress_lock:
        _progress_log.append(entry)


def get_progress() -> list[dict]:
    with _progress_lock:
        return list(_progress_log)


def clear_progress() -> None:
    with _progress_lock:
        _progress_log.clear()


# ── Discovery loop ────────────────────────────────────────────────────────────

def _run_loop(interval_minutes: int, scan_immediately: bool = False) -> None:
    """Worker loop: sleep → discover → repeat. Exits when _stop_event is set."""
    # Sleep first unless explicitly told to scan immediately (trigger_now)
    if not scan_immediately:
        for _ in range(interval_minutes * 60):
            if _stop_event.is_set() or _trigger_event.is_set():
                break
            time.sleep(1)
        _trigger_event.clear()

    while not _stop_event.is_set():
        try:
            clear_progress()
            _trigger_event.clear()
            scan_started = datetime.utcnow()
            triggered_by = _read_state().get("triggered_by", "system")
            _write_state({
                "status":     "running",
                "started_at": scan_started.isoformat(),
                "scan_started_at": scan_started.isoformat(),
                "error":      None,
            })
            # Old 'new' jobs naturally fall out of New tab via scan timestamp filter
            # No status change needed - they remain discoverable in All tab
            _add_progress(f"Discovery started at {datetime.utcnow().strftime('%H:%M:%S')}")
            log.info("[BG] Starting discovery run…")

            try:
                from src.runner import run_discovery
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _current_loop = loop  # Store so stop_discovery can interrupt it

                async def _cancellable_run():
                    return await run_discovery(headed=False, on_progress=_add_progress)

                task = loop.create_task(_cancellable_run())

                def _check_stop():
                    if _stop_event.is_set() and not task.done():
                        task.cancel()
                        _add_progress("Discovery stopped by user")

                # Check stop signal every 0.5s
                async def _run_with_stop_check():
                    while not task.done():
                        if _stop_event.is_set():
                            task.cancel()
                            _add_progress("Discovery stopped by user")
                            break
                        await asyncio.sleep(0.5)
                    try:
                        return await task
                    except asyncio.CancelledError:
                        return 0

                new_count = loop.run_until_complete(_run_with_stop_check())
                _current_loop = None
                loop.close()

                _write_state({
                    "status":              "idle",
                    "last_run":            datetime.utcnow().isoformat(),
                    "last_scan_completed_at": scan_started.isoformat(),
                    "last_new_count":      new_count,
                    "next_run_in_seconds": interval_minutes * 60,
                    "error":               None,
                })
                log.info(f"[BG] Done — {new_count} new jobs. Sleeping {interval_minutes}m.")

            except Exception as e:
                log.error(f"[BG] Discovery error: {e}")
                _add_progress(f"ERROR: {e}")
                _write_state({
                    "status":         "idle",
                    "last_run":       datetime.utcnow().isoformat(),
                    "last_new_count": 0,
                    "error":          str(e),
                })

            # Sleep in 1-second ticks so we can react to stop/trigger quickly
            for _ in range(interval_minutes * 60):
                if _stop_event.is_set() or _trigger_event.is_set():
                    break
                time.sleep(1)

        except Exception as e:
            log.error(f"[BG] Loop crashed: {e}")
            time.sleep(30)

    _write_state({"status": "idle"})
    log.info("[BG] Discovery daemon stopped.")


# ── Public API ────────────────────────────────────────────────────────────────

def ensure_running(interval_minutes: int = 60) -> None:
    """Start the background thread if not already running. Safe to call multiple times."""
    global _thread
    _stop_event.clear()
    if _thread is not None and _thread.is_alive():
        return
    _write_state({"status": "starting", "interval_minutes": interval_minutes})
    _thread = threading.Thread(
        target=_run_loop,
        args=(interval_minutes, False),
        daemon=True,
        name="discovery-daemon",
    )
    _thread.start()
    log.info(f"[BG] Discovery daemon started (interval={interval_minutes}m)")


def stop_discovery() -> None:
    """Signal the daemon to stop and cancel any in-progress scan immediately."""
    global _thread, _current_loop
    _stop_event.set()
    _trigger_event.set()
    # Cancel the running asyncio loop if active
    if _current_loop is not None and _current_loop.is_running():
        _current_loop.call_soon_threadsafe(_current_loop.stop)
    _write_state({"status": "idle"})
    log.info("[BG] Stop signal sent — scan cancelled.")


def trigger_now(triggered_by: str = "system") -> bool:
    """Skip the current sleep interval and run discovery immediately."""
    global _thread
    state    = _read_state()
    interval = state.get("interval_minutes", 60)
    _write_state({"triggered_by": triggered_by})

    if _thread is None or not _thread.is_alive():
        _stop_event.clear()
        _thread = threading.Thread(
            target=_run_loop, args=(interval, True), daemon=True, name="discovery-daemon"
        )
        _thread.start()
        return True

    # Daemon is sleeping — wake it up
    _trigger_event.set()
    return True
