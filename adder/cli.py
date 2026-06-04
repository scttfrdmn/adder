"""adder CLI — delegates to burst-core for AWS operations."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import click

from . import __version__
from .config import load as load_config, save as save_config


def _require_burst_core() -> None:
    if not shutil.which("burst-core") and not _burst_core_home_path().exists():
        click.echo(
            "burst-core not found in PATH.\n"
            "Install: curl -fsSL https://burst-core.dev/install | sh",
            err=True,
        )
        sys.exit(1)


def _burst_core_bin() -> str:
    home_path = _burst_core_home_path()
    if home_path.exists():
        return str(home_path)
    return "burst-core"


def _burst_core_home_path():
    from pathlib import Path

    return Path.home() / ".burst" / "bin" / "burst-core"


@click.group()
def main() -> None:
    """adder — Cloud bursting for Python."""


@main.command()
@click.option("--region", default=None, help="AWS region")
@click.option("--profile", default=None, help="AWS profile")
def setup(region: str | None, profile: str | None) -> None:
    """Run burst-core setup to provision AWS resources."""
    _require_burst_core()
    cmd = [_burst_core_bin(), "setup"]
    if region:
        cmd += ["--region", region]
    if profile:
        cmd += ["--profile", profile]
    subprocess.run(cmd, check=True)


@main.command()
def status() -> None:
    """Check status of AWS resources."""
    _require_burst_core()
    subprocess.run([_burst_core_bin(), "status"], check=True)


@main.group()
def session() -> None:
    """Manage burst sessions."""


@session.command(name="list")
def session_list() -> None:
    """List all sessions."""
    _require_burst_core()
    subprocess.run([_burst_core_bin(), "session", "list"], check=True)


@session.command(name="status")
@click.argument("session_id")
def session_status(session_id: str) -> None:
    """Show status of a session."""
    _require_burst_core()
    subprocess.run([_burst_core_bin(), "session", "status", session_id], check=True)


@session.command(name="cleanup")
@click.argument("session_id")
@click.option("--force", is_flag=True, help="Force cleanup even if session is not complete")
def session_cleanup(session_id: str, force: bool) -> None:
    """Clean up a session's S3 artifacts."""
    _require_burst_core()
    cmd = [_burst_core_bin(), "session", "cleanup", session_id]
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True)


@main.group()
def config() -> None:
    """Manage adder configuration."""


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a config value in ~/.burst/config.json."""
    cfg = load_config()
    if not hasattr(cfg, key):
        click.echo(f"Unknown config key: {key}", err=True)
        sys.exit(1)
    # Type-coerce value to match the field type
    current = getattr(cfg, key)
    if isinstance(current, bool):
        coerced = value.lower() in ("true", "1", "yes")
    elif isinstance(current, int):
        coerced = int(value)
    elif isinstance(current, float):
        coerced = float(value)
    else:
        coerced = value
    setattr(cfg, key, coerced)
    save_config(cfg)
    click.echo(f"Set {key} = {coerced!r}")


@config.command(name="show")
def config_show() -> None:
    """Print current config."""
    import dataclasses

    cfg = load_config()
    click.echo(json.dumps(dataclasses.asdict(cfg), indent=2))


@main.command()
def version() -> None:
    """Print version information."""
    click.echo(f"adder {__version__}")
    bc = shutil.which("burst-core") or str(_burst_core_home_path())
    try:
        result = subprocess.run([bc, "version"], capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(f"burst-core {result.stdout.strip()}")
    except Exception:
        click.echo("burst-core: not found")
