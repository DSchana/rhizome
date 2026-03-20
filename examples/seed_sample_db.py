"""Create a sample database with test data for exploration.

Usage:
    uv run python examples/seed_sample_db.py

This creates (or recreates) ``explore.db`` in the project root with a handful
of topics, knowledge entries, and tags so you have real data to poke at with
the ``sqlite3`` CLI.
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rhizome.db import (
    KnowledgeEntry,
    KnowledgeEntryTag,
    RelatedKnowledgeEntries,
    Tag,
    Topic,
    get_session_factory,
    init_db,
)
from rhizome.db.models import EntryType

DB_PATH = Path(__file__).resolve().parent.parent / "explore.db"


async def main() -> None:
    # Wipe any existing file so the script is fully repeatable.
    DB_PATH.unlink(missing_ok=True)

    engine = await init_db(DB_PATH)
    factory = get_session_factory(engine)

    async with factory() as session:
        # -- Topics (depth 1: roots) --
        motions = Topic(name="motions", description="Moving the cursor around")
        operators = Topic(name="operators", description="Actions that operate on text")
        iam = Topic(name="IAM", description="Identity and Access Management")
        session.add_all([motions, operators, iam])
        await session.flush()

        # -- Topics (depth 2) --
        word_motions = Topic(parent_id=motions.id, name="word motions", description="Moving by words")
        char_motions = Topic(parent_id=motions.id, name="character motions", description="Moving by characters")
        search_motions = Topic(parent_id=motions.id, name="search motions", description="Moving by search")
        delete_op = Topic(parent_id=operators.id, name="delete", description="Deleting text")
        change_op = Topic(parent_id=operators.id, name="change", description="Changing text")
        yank_op = Topic(parent_id=operators.id, name="yank", description="Yanking (copying) text")
        iam_policies = Topic(parent_id=iam.id, name="policies", description="IAM policy documents")
        iam_roles = Topic(parent_id=iam.id, name="roles", description="IAM roles and trust")
        session.add_all([word_motions, char_motions, search_motions, delete_op, change_op, yank_op, iam_policies, iam_roles])
        await session.flush()

        # -- Topics (depth 3) --
        w_motion = Topic(parent_id=word_motions.id, name="w / W", description="Forward word motion")
        b_motion = Topic(parent_id=word_motions.id, name="b / B", description="Backward word motion")
        e_motion = Topic(parent_id=word_motions.id, name="e / E", description="End-of-word motion")
        f_search = Topic(parent_id=search_motions.id, name="f / F", description="Find character on line")
        slash_search = Topic(parent_id=search_motions.id, name="/ and ?", description="Pattern search")
        policy_structure = Topic(parent_id=iam_policies.id, name="policy structure", description="Effect, Action, Resource")
        policy_conditions = Topic(parent_id=iam_policies.id, name="conditions", description="Condition keys and operators")
        session.add_all([w_motion, b_motion, e_motion, f_search, slash_search, policy_structure, policy_conditions])
        await session.flush()

        # -- Knowledge entries --
        e_word = KnowledgeEntry(
            topic_id=w_motion.id,
            title="Word motion",
            content="w moves forward one word",
            entry_type=EntryType.fact,
        )
        e_motion_def = KnowledgeEntry(
            topic_id=motions.id,
            title="Motion definition",
            content="A motion is a command that moves the cursor",
            entry_type=EntryType.exposition,
        )
        e_delete = KnowledgeEntry(
            topic_id=delete_op.id,
            title="Delete operator",
            content="d is the delete operator",
            entry_type=EntryType.fact,
        )
        e_compose = KnowledgeEntry(
            topic_id=operators.id,
            title="Operator-motion composition",
            content="Operators compose with motions: dw deletes a word",
            entry_type=EntryType.overview,
        )
        e_iam = KnowledgeEntry(
            topic_id=policy_structure.id,
            title="IAM Policy",
            content="A JSON document that defines permissions",
            entry_type=EntryType.exposition,
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
