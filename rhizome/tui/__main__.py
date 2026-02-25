"""Entry point: ``uv run python -m rhizome.tui``."""

import asyncio

import rich_click as click

from rhizome.config import get_default_db_path
from rhizome.db import init_db
from rhizome.tui.app import CurriculumApp


@click.command()
@click.option(
    "--db",
    default=None,
    type=click.Path(dir_okay=False),
    help="Path to the SQLite database file. [default: platform data dir or $RHIZOME_DB]",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging of agent stream events.")
def main(db: str | None, debug: bool) -> None:
    """Launch the rhizome TUI."""
    db_path = db or str(get_default_db_path())
    asyncio.run(init_db(db_path))
    app = CurriculumApp(db_path=db_path, debug=debug)
    app.run()


main()
