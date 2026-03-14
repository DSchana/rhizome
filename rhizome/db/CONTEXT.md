# rhizome/db/

Database layer. Defines the ORM schema and provides async engine/session management.

## Files

- **models.py** — SQLAlchemy ORM models (all use `Mapped`/`mapped_column` typed syntax):
  - `Curriculum` — top-level subject area (unique name). Has topics via `CurriculumTopic` junction (many-to-many). Deleting a curriculum removes junction rows but not the topics themselves.
  - `CurriculumTopic` — junction table: curriculum ↔ topic (many-to-many with `position` for ordering). Composite PK on (`curriculum_id`, `topic_id`).
  - `Topic` — knowledge area organized as a tree (adjacency list via `parent_id` self-FK). Root topics have `parent_id=NULL`. Sibling names must be unique (`UniqueConstraint("parent_id", "name")`). Owns entries via cascade delete.
  - `KnowledgeEntry` — core knowledge unit (fact/concept/definition). Has `title`, `content`, `additional_notes`, `entry_type`, `difficulty` (nullable int), `speed_testable` (bool, default false). Connected to tags (many-to-many) and other entries (directed graph).
  - `Tag` — freeform label (unique, lowercase-normalized).
  - `KnowledgeEntryTag` — junction table for entry-tag many-to-many.
  - `RelatedKnowledgeEntries` — directed edge between two entries with a `relationship_type` (e.g. "depends_on", "example_of"). Has a CHECK constraint preventing self-loops; cycles are prevented at the tool layer.
  - `ReviewSession` — a review session covering a set of topics and entries. Has `ephemeral` (bool, default false) to flag sessions that should be cleaned up periodically. Tracks `created_at` (auto), `started_at` (auto), and optional `completed_at`. Has optional `additional_args` (JSON) for flexible metadata, optional `user_instructions` (text) for user-provided session guidance, and optional `final_summary` (text) for post-session thoughts. Has topics (M2M via `ReviewSessionTopic`), entries (M2M via `ReviewSessionEntry`), interactions (one-to-many cascade), and flashcards (one-to-many cascade — flashcards created during this session).
  - `ReviewSessionTopic` — junction table: review session ↔ topic. Composite PK on (`session_id`, `topic_id`).
  - `ReviewSessionEntry` — junction table: review session ↔ entry. Composite PK on (`session_id`, `entry_id`).
  - `Flashcard` — reusable question template tied to a topic (`topic_id` FK, indexed) and optionally to the review session that created it (`session_id` FK, nullable, indexed). Has `question_text`, `answer_text`, and optional `testing_notes` (instructions for critiquing user responses). Associated to knowledge entries via `FlashcardEntry` junction (M2M, cascade delete-orphan). When a parent ReviewSession is deleted (e.g. ephemeral cleanup), its flashcards cascade-delete as well.
  - `FlashcardEntry` — junction table: flashcard ↔ knowledge entry. Composite PK on (`flashcard_id`, `entry_id`).
  - `ReviewInteraction` — one question-answer exchange within a review session. Has optional `flashcard_id` FK (indexed) — present for flashcard-based reviews, null for conversational exchanges. Has `question_text`, `user_response`, optional `feedback` and `score` (0-5, CHECK constraint), and `position` for ordering. References entries tested via `ReviewInteractionEntry` junction.
  - `ReviewInteractionEntry` — junction table: review interaction ↔ entry. Composite PK on (`interaction_id`, `entry_id`).

- **engine.py** — Three functions:
  - `get_engine(db_path)` — creates an `AsyncEngine` using `sqlite+aiosqlite`.
  - `get_session_factory(engine)` — returns an `async_sessionmaker` with `expire_on_commit=False`.
  - `init_db(db_path)` — creates all tables (idempotent) and returns the engine.

## `__init__.py` exports

All 15 model classes (`Base`, `Curriculum`, `CurriculumTopic`, `Topic`, `KnowledgeEntry`, `Tag`, `KnowledgeEntryTag`, `RelatedKnowledgeEntries`, `Flashcard`, `FlashcardEntry`, `ReviewSession`, `ReviewSessionTopic`, `ReviewSessionEntry`, `ReviewInteraction`, `ReviewInteractionEntry`), plus `get_engine`, `get_session_factory`, and `init_db`. Import from `rhizome.db` directly.
