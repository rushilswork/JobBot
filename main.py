"""
JobBot CLI
  python main.py dashboard   — start the web dashboard (default port 8000)
  python main.py discover    — run a discovery pass manually
  python main.py status      — print queue stats
"""
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


@click.group()
def cli():
    """JobBot — automated job discovery & application assistant"""
    pass


@cli.command()
@click.option("--port", default=8000, show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
def dashboard(port, host):
    """Start the dashboard (opens at http://localhost:{port})"""
    import webbrowser, threading, time, uvicorn
    from src.api import app

    def _open():
        time.sleep(1.5)
        webbrowser.open(f"http://{host}:{port}")
    threading.Thread(target=_open, daemon=True).start()

    from src.database import init_db
    from src.utils import load_config
    init_db()

    click.echo(f"\n  JobBot dashboard → http://{host}:{port}\n")
    click.echo("  Discovery is paused — click Scan in the dashboard to start.\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.option("--headed", is_flag=True, default=False)
def discover(headed):
    """Run a discovery pass across all companies and portals."""
    import asyncio
    from src.runner import run_discovery
    from src.database import init_db
    init_db()
    click.echo("Starting discovery…")
    count = asyncio.run(run_discovery(headed=headed))
    click.echo(f"Done — {count} new job(s) added.")


@cli.command()
def status():
    """Print job queue stats."""
    from src.database import Job, init_db, get_session
    from rich.table import Table
    from rich.console import Console
    init_db()
    session = get_session()
    jobs = session.query(Job).all()
    cnts = {}
    for j in jobs:
        cnts[j.status] = cnts.get(j.status, 0) + 1
    c = Console()
    t = Table(title="Job Queue")
    t.add_column("Status"); t.add_column("Count", justify="right")
    for s, n in sorted(cnts.items()): t.add_row(s, str(n))
    c.print(t)
    session.close()


if __name__ == "__main__":
    cli()
