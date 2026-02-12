"""Create a sample database with test data for exploration.

Usage:
    uv run python examples/seed_sample_db.py

This creates (or recreates) ``explore.db`` in the project root with a handful
of curricula, topics, knowledge entries, and tags so you have real data to
poke at with the ``sqlite3`` CLI.
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum_app.db import (
    Curriculum,
    KnowledgeEntry,
    KnowledgeEntryTag,
    RelatedKnowledgeEntries,
    Tag,
    Topic,
    get_session_factory,
    init_db,
)

DB_PATH = Path(__file__).resolve().parent.parent / "explore.db"


async def main() -> None:
    # Wipe any existing file so the script is fully repeatable.
    DB_PATH.unlink(missing_ok=True)

    engine = await init_db(DB_PATH)
    factory = get_session_factory(engine)

    async with factory() as session:
        # -- Curricula --
        vim = Curriculum(name="vim", description="The Vim text editor")
        aws = Curriculum(name="aws", description="Amazon Web Services")
        session.add_all([vim, aws])
        await session.flush()

        # -- Topics --
        motions = Topic(
            curriculum_id=vim.id,
            name="motions",
            description="Moving the cursor around",
        )
        operators = Topic(
            curriculum_id=vim.id,
            name="operators",
            description="Actions that operate on text",
        )
        iam = Topic(
            curriculum_id=aws.id,
            name="IAM",
            description="Identity and Access Management",
        )
        session.add_all([motions, operators, iam])
        await session.flush()

        # -- Knowledge entries --
        e_word = KnowledgeEntry(
            topic_id=motions.id,
            title="Word motion",
            content="w moves forward one word",
            entry_type="fact",
        )
        e_motion_def = KnowledgeEntry(
            topic_id=motions.id,
            title="Motion definition",
            content="A motion is a command that moves the cursor",
            entry_type="definition",
        )
        e_delete = KnowledgeEntry(
            topic_id=operators.id,
            title="Delete operator",
            content="d is the delete operator",
            entry_type="fact",
        )
        e_compose = KnowledgeEntry(
            topic_id=operators.id,
            title="Operator-motion composition",
            content="Operators compose with motions: dw deletes a word",
            entry_type="concept",
        )
        e_iam = KnowledgeEntry(
            topic_id=iam.id,
            title="IAM Policy",
            content="A JSON document that defines permissions",
            entry_type="definition",
        )
        entries = [e_word, e_motion_def, e_delete, e_compose, e_iam]
        session.add_all(entries)
        await session.flush()

        # -- Tags --
        beginner = Tag(name="beginner")
        core = Tag(name="core")
        session.add_all([beginner, core])
        await session.flush()

        # -- Tag associations --
        session.add_all(
            [
                KnowledgeEntryTag(
                    knowledge_entry_id=e_word.id, tag_id=beginner.id
                ),
                KnowledgeEntryTag(
                    knowledge_entry_id=e_word.id, tag_id=core.id
                ),
                KnowledgeEntryTag(
                    knowledge_entry_id=e_delete.id, tag_id=beginner.id
                ),
            ]
        )

        # -- Related entries --
        # "Operator-motion composition" depends on "Motion definition"
        session.add(
            RelatedKnowledgeEntries(
                source_entry_id=e_compose.id,
                target_entry_id=e_motion_def.id,
                relationship_type="depends_on",
            )
        )
        # "Delete operator" is an example of "Operator-motion composition"
        session.add(
            RelatedKnowledgeEntries(
                source_entry_id=e_delete.id,
                target_entry_id=e_compose.id,
                relationship_type="example_of",
            )
        )

        await session.commit()

    await engine.dispose()
    print(f"Sample database created: {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
