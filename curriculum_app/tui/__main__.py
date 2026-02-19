"""Entry point: ``uv run python -m curriculum_app.tui``."""

import asyncio

import rich_click as click

from curriculum_app.config import get_default_db_path
from curriculum_app.db import init_db
from curriculum_app.tui.app import CurriculumApp


@click.command()
@click.option(
    "--db",
    default=None,
    type=click.Path(dir_okay=False),
    help="Path to the SQLite database file. [default: platform data dir or $CURRICULUM_APP_DB]",
)
def main(db: str | None) -> None:
    """Launch the curriculum-app TUI."""
    db_path = db or str(get_default_db_path())
    asyncio.run(init_db(db_path))
    app = CurriculumApp(db_path=db_path)
    app.run()


main()
