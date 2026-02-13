"""Entry point: ``uv run python -m curriculum_app.tui``."""

from curriculum_app.tui.app import CurriculumApp

app = CurriculumApp()
app.run()
