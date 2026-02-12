"""Exercise every tool function against a fresh explore.db.

Usage:
    uv run python examples/exercise_tools.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum_app.db import get_session_factory, init_db
from curriculum_app.tools import (
    CycleError,
    add_relation,
    create_curriculum,
    create_entry,
    create_tag,
    create_topic,
    delete_curriculum,
    delete_entry,
    delete_topic,
    get_curriculum,
    get_dependency_chain,
    get_entries_by_tag,
    get_entry,
    get_related_entries,
    get_topic,
    list_curricula,
    list_entries,
    list_tags,
    list_topics,
    remove_relation,
    search_entries,
    tag_entry,
    untag_entry,
    update_curriculum,
    update_entry,
    update_topic,
)

DB_PATH = Path(__file__).resolve().parent.parent / "explore.db"
passed = 0
failed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  FAIL  {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        ok(label)
    else:
        fail(label, detail)


async def main() -> None:
    DB_PATH.unlink(missing_ok=True)
    engine = await init_db(DB_PATH)
    factory = get_session_factory(engine)

    # ── Curricula ───────────────────────────────────────────────
    print("\n=== Curricula ===")
    async with factory() as s:
        c = await create_curriculum(s, name="vim", description="The Vim editor")
        check(c.id is not None, "create_curriculum returns id")
        check(c.name == "vim", "create_curriculum sets name")

        fetched = await get_curriculum(s, c.id)
        check(fetched is not None and fetched.name == "vim", "get_curriculum")

        check(await get_curriculum(s, 9999) is None, "get_curriculum returns None for missing")

        await create_curriculum(s, name="aws")
        curricula = await list_curricula(s)
        check(len(curricula) == 2, f"list_curricula returns 2 (got {len(curricula)})")

        updated = await update_curriculum(s, c.id, name="Vim", description="Vim editor")
        check(updated.name == "Vim", "update_curriculum changes name")
        check(updated.description == "Vim editor", "update_curriculum changes description")

        await s.commit()

    # ── Topics ──────────────────────────────────────────────────
    print("\n=== Topics ===")
    async with factory() as s:
        curricula = await list_curricula(s)
        vim_id = next(c.id for c in curricula if c.name == "Vim")

        t = await create_topic(s, curriculum_id=vim_id, name="motions")
        check(t.id is not None, "create_topic returns id")

        await create_topic(s, curriculum_id=vim_id, name="operators")
        topics = await list_topics(s, vim_id)
        check(len(topics) == 2, f"list_topics returns 2 (got {len(topics)})")

        fetched = await get_topic(s, t.id)
        check(fetched is not None, "get_topic")

        updated = await update_topic(s, t.id, description="Cursor movement")
        check(updated.description == "Cursor movement", "update_topic")

        await s.commit()

    # ── Entries ──────────────────────────────────────────────────
    print("\n=== Entries ===")
    async with factory() as s:
        topics = await list_topics(s, vim_id)
        motions_id = next(t.id for t in topics if t.name == "motions")
        operators_id = next(t.id for t in topics if t.name == "operators")

        e1 = await create_entry(s, topic_id=motions_id, title="Word motion", content="w moves forward one word")
        e2 = await create_entry(s, topic_id=motions_id, title="Motion definition", content="A motion moves the cursor", entry_type="definition")
        e3 = await create_entry(s, topic_id=operators_id, title="Delete operator", content="d is the delete operator")
        e4 = await create_entry(s, topic_id=operators_id, title="Operator-motion composition", content="dw deletes a word", entry_type="concept")
        check(e1.id is not None, "create_entry returns id")
        check(e2.entry_type == "definition", "create_entry respects entry_type")

        fetched = await get_entry(s, e1.id)
        check(fetched is not None, "get_entry")

        entries = await list_entries(s, motions_id)
        check(len(entries) == 2, f"list_entries for motions (got {len(entries)})")

        updated = await update_entry(s, e1.id, title="Word motion (w)")
        check(updated.title == "Word motion (w)", "update_entry")

        # Search
        results = await search_entries(s, "motion")
        check(len(results) >= 2, f"search_entries('motion') finds >=2 (got {len(results)})")

        results = await search_entries(s, "delete", topic_id=operators_id)
        check(len(results) >= 1, f"search_entries scoped to topic (got {len(results)})")

        results = await search_entries(s, "word", curriculum_id=vim_id)
        check(len(results) >= 1, f"search_entries scoped to curriculum (got {len(results)})")

        await s.commit()

    # ── Tags ────────────────────────────────────────────────────
    print("\n=== Tags ===")
    async with factory() as s:
        tag = await create_tag(s, name="Beginner")
        check(tag.name == "beginner", "create_tag normalizes to lowercase")

        await tag_entry(s, entry_id=e1.id, tag_name="beginner")
        await tag_entry(s, entry_id=e3.id, tag_name="beginner")
        await tag_entry(s, entry_id=e1.id, tag_name="core")  # auto-creates "core"

        tags = await list_tags(s)
        check(len(tags) == 2, f"list_tags returns 2 (got {len(tags)})")

        tagged = await get_entries_by_tag(s, "beginner")
        check(len(tagged) == 2, f"get_entries_by_tag('beginner') returns 2 (got {len(tagged)})")

        tagged_scoped = await get_entries_by_tag(s, "beginner", curriculum_id=vim_id)
        check(len(tagged_scoped) == 2, f"get_entries_by_tag scoped to curriculum (got {len(tagged_scoped)})")

        await untag_entry(s, entry_id=e1.id, tag_name="beginner")
        tagged_after = await get_entries_by_tag(s, "beginner")
        check(len(tagged_after) == 1, f"untag_entry removes association (got {len(tagged_after)})")

        # untag non-existent — should not raise
        await untag_entry(s, entry_id=e1.id, tag_name="nonexistent")
        ok("untag_entry no-op for missing tag")

        await s.commit()

    # ── Relations ───────────────────────────────────────────────
    print("\n=== Relations ===")
    async with factory() as s:
        # e4 (composition) depends_on e2 (motion definition)
        rel = await add_relation(s, source_entry_id=e4.id, target_entry_id=e2.id, relationship_type="depends_on")
        check(rel.source_entry_id == e4.id, "add_relation creates edge")

        # e3 (delete) example_of e4 (composition)
        await add_relation(s, source_entry_id=e3.id, target_entry_id=e4.id, relationship_type="example_of")

        related = await get_related_entries(s, e4.id)
        check(len(related) == 1, f"get_related_entries returns 1 outgoing (got {len(related)})")

        # Cycle detection: e2 -> e4 would close the loop (e4 -> e2 already exists)
        try:
            await add_relation(s, source_entry_id=e2.id, target_entry_id=e4.id, relationship_type="depends_on")
            fail("cycle detection", "should have raised CycleError")
        except CycleError:
            ok("cycle detection raises CycleError")

        # Dependency chain: e3 -> e4 -> e2  (e3 depends_on nothing, but e3 example_of e4)
        # Only follows depends_on, so chain from e4 should be [e2]
        chain = await get_dependency_chain(s, e4.id)
        check(len(chain) == 1, f"get_dependency_chain from e4 (got {len(chain)})")
        check(chain[0]["entry"].id == e2.id, "dependency chain contains e2")
        check(chain[0]["depth"] == 1, "dependency chain depth == 1")

        # Remove relation
        await remove_relation(s, source_entry_id=e4.id, target_entry_id=e2.id)
        related_after = await get_related_entries(s, e4.id)
        check(len(related_after) == 0, "remove_relation removes edge")

        await s.commit()

    # ── Delete cascades ─────────────────────────────────────────
    print("\n=== Delete ===")
    async with factory() as s:
        await delete_entry(s, e1.id)
        check(await get_entry(s, e1.id) is None, "delete_entry removes entry")

        await delete_topic(s, operators_id)
        check(await get_topic(s, operators_id) is None, "delete_topic removes topic")

        # entries under operators should be gone
        entries_after = await list_entries(s, operators_id)
        check(len(entries_after) == 0, "delete_topic cascades to entries")

        await delete_curriculum(s, vim_id)
        check(await get_curriculum(s, vim_id) is None, "delete_curriculum removes curriculum")

        await s.commit()

    await engine.dispose()

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("  All checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
