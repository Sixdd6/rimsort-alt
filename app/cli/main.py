"""
Main CLI entry point for RimSort.

This module defines the Click command group and registers all subcommands.
"""

import click

from app.cli.build_db import build_db
from app.utils.app_info import AppInfo
from app.utils.constants import APP_DISPLAY_NAME


@click.group()
@click.version_option(version=AppInfo().app_version, prog_name=APP_DISPLAY_NAME)
def cli() -> None:
    """RimSort - RimWorld mod manager CLI

    Headless tools for managing RimWorld mods, building databases, and more.

    Global flags (processed before CLI):
      --disable-updater    Disable automatic update checks (same as RIMSORT_DISABLE_UPDATER env var)
    """


# Register subcommands
cli.add_command(build_db)


if __name__ == "__main__":
    cli()
