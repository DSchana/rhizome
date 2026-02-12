# Database Schema Proposal (v2) — Knowledge Layer

## Context

This is the foundational data layer for curriculum-app. The database and a set of queries will be exposed as **tools for an LLM agent**. The agent reads/writes knowledge entries and uses them to generate quizzes, speed tests, etc. on the fly — the database stores *knowledge*, not quiz state.

## Technology Choices

Same as v1: **SQLite** + **SQLAlchemy 2.x** (async via **aiosqlite**).

SQLite is the right fit for a local single-user (or small group) TUI app. The agent interacts with the database through tool functions, not raw SQL.

```
"sqlalchemy[asyncio]>=2.0",
"aiosqlite>=0.20.0",
```

---

## Tables

6 tables, one domain:

| Table | Purpose |
|---|---|
| `curriculum` | Top-level subject area |
| `topic` | Sub-area within a curriculum |
| `knowledge_entry` | A single learned concept, fact, or definition |
| `tag` | Freeform cross-cutting label |
| `knowledge_entry_tag` | Junction: entry ↔ tag |
| `related_knowledge_entries` | Directed graph of relationships between entries |

---

### `curriculum`

A subject area (e.g., "gcloud", "vim", "AWS").

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `name` | TEXT | NOT NULL, UNIQUE |
| `description` | TEXT | |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now |

---

### `topic`

A sub-area within a curriculum (e.g., "vim motions", "IAM policies").

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `curriculum_id` | INTEGER | FK → `curriculum.id`, NOT NULL |
| `name` | TEXT | NOT NULL |
| `description` | TEXT | |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now |

UNIQUE(`curriculum_id`, `name`)

---

### `knowledge_entry`

The core unit of knowledge. Each row is one thing worth knowing.

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `topic_id` | INTEGER | FK → `topic.id`, NOT NULL |
| `title` | TEXT | NOT NULL |
| `content` | TEXT | NOT NULL |
| `additional_notes` | TEXT | NOT NULL |
| `entry_type` | TEXT | NOT NULL, DEFAULT `'fact'` |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now |

`entry_type` is one of: **`fact`**, **`concept`**, **`definition`**.

- **fact** — a concrete, testable piece of knowledge (e.g., "`dd` deletes a line in vim")
- **concept** — a broader idea that ties facts together (e.g., "vim operators compose with motions")
- **definition** — a term and its meaning (e.g., "a *motion* in vim is a command that moves the cursor")

Index: `ix_knowledge_entry_topic_id` on `topic_id`

---

### `tag`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `name` | TEXT | NOT NULL, UNIQUE |

Tag names are lowercase and normalized.

---

### `knowledge_entry_tag`

Junction table: many-to-many between entries and tags.

| Column | Type | Constraints |
|---|---|---|
| `knowledge_entry_id` | INTEGER | FK → `knowledge_entry.id`, NOT NULL |
| `tag_id` | INTEGER | FK → `tag.id`, NOT NULL |

PK(`knowledge_entry_id`, `tag_id`)

---

### `related_knowledge_entries`

A directed edge between two knowledge entries. Models relationships like "A depends on B", "A is an example of B", etc. The graph should be acyclic in practice, but this is **not enforced at the database level** (see note below).

| Column | Type | Constraints |
|---|---|---|
| `source_entry_id` | INTEGER | FK → `knowledge_entry.id`, NOT NULL |
| `target_entry_id` | INTEGER | FK → `knowledge_entry.id`, NOT NULL |
| `relationship_type` | TEXT | NOT NULL |

PK(`source_entry_id`, `target_entry_id`)

CHECK(`source_entry_id != target_entry_id`) — prevents self-loops.

`relationship_type` values (initial set, extensible):
- **`depends_on`** — source requires understanding of target
- **`example_of`** — source is a concrete example of target
- **`related_to`** — general association

#### On acyclicity

Enforcing "no cycles" in a general directed graph is not expressible as a SQL constraint — it requires a recursive traversal to verify. The right place to enforce this is in the **tool layer**: before inserting an edge `A → B`, run a reachability check from `B` to `A`. If `B` can already reach `A`, the insertion would create a cycle and should be rejected. SQLite supports recursive CTEs, so this check is a single query:

```sql
-- Before inserting edge (A → B), check if B can reach A.
-- If this returns any rows, the edge would create a cycle.
WITH RECURSIVE reachable(entry_id) AS (
    SELECT :target_entry_id
    UNION
    SELECT r.target_entry_id
    FROM related_knowledge_entries r
    JOIN reachable ON r.source_entry_id = reachable.entry_id
)
SELECT 1 FROM reachable WHERE entry_id = :source_entry_id LIMIT 1;
```

---

## Entity-Relationship Diagram

```
curriculum 1──* topic 1──* knowledge_entry *──* tag
                                  │
                                  │ (related_knowledge_entries)
                                  ▼
                          knowledge_entry
                       [directed graph edges]
```

---

## Example Agent Tool Queries

These are the queries that would back the agent's tool functions.

### Get all entries for a topic

```sql
SELECT id, title, content, entry_type
FROM knowledge_entry
WHERE topic_id = :topic_id
ORDER BY created_at;
```

### Get entries by tag across a curriculum

```sql
SELECT ke.id, ke.title, ke.content, ke.entry_type, t.name AS topic_name
FROM knowledge_entry ke
JOIN topic t ON ke.topic_id = t.id
JOIN knowledge_entry_tag ket ON ket.knowledge_entry_id = ke.id
JOIN tag ON ket.tag_id = tag.id
WHERE t.curriculum_id = :curriculum_id
  AND tag.name = :tag_name;
```

### Get related entries (one level deep)

```sql
SELECT ke.id, ke.title, ke.entry_type, r.relationship_type
FROM related_knowledge_entries r
JOIN knowledge_entry ke ON r.target_entry_id = ke.id
WHERE r.source_entry_id = :entry_id;
```

### Get full dependency chain (recursive)

```sql
WITH RECURSIVE deps(entry_id, depth) AS (
    SELECT target_entry_id, 1
    FROM related_knowledge_entries
    WHERE source_entry_id = :entry_id
      AND relationship_type = 'depends_on'
    UNION
    SELECT r.target_entry_id, deps.depth + 1
    FROM related_knowledge_entries r
    JOIN deps ON r.source_entry_id = deps.entry_id
    WHERE r.relationship_type = 'depends_on'
      AND deps.depth < 10
)
SELECT ke.id, ke.title, ke.entry_type, deps.depth
FROM deps
JOIN knowledge_entry ke ON deps.entry_id = ke.id
ORDER BY deps.depth;
```

### Search entries by keyword

```sql
SELECT id, title, content, entry_type
FROM knowledge_entry
WHERE topic_id = :topic_id
  AND (title LIKE '%' || :query || '%' OR content LIKE '%' || :query || '%');
```
