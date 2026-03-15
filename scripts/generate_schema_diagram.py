"""Generate an ER diagram from SQLAlchemy models using eralchemy2.

Usage: uv run python -m scripts.generate_schema_diagram
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eralchemy2 import render_er

from rhizome.db.models import Base

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
OUTPUT_PATH = DOCS_DIR / "schema.png"


def main():
    render_er(Base, str(OUTPUT_PATH))
    print(f"Schema diagram written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
