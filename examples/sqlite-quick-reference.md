# SQLite Quick Reference

A beginner-friendly guide to exploring your curriculum-app database with the `sqlite3` command-line tool.

## Setup

Generate a sample database to explore:

```bash
uv run python examples/seed_sample_db.py
```

This creates `explore.db` in the project root. Open it with:

```bash
sqlite3 explore.db
```

You're now at the `sqlite>` prompt. Everything below is typed there.

## Two kinds of commands

| Kind | Starts with | Ends with | What it's for |
|---|---|---|---|
| Dot command | `.` | nothing | Controlling the sqlite3 tool itself |
| SQL statement | a keyword (`SELECT`, etc.) | `;` | Querying and modifying data |

If you type a `SELECT` and nothing happens, you probably forgot the `;`.

## Making output readable

Run these two commands first — they stay active for the whole session:

```
.mode column
.headers on
```

Or for box-drawn tables (nicer but wider):

```
.mode box
.headers on
```

## Orienting yourself

**List all tables:**

```
.tables
```

**See the structure of a single table:**

```
.schema curriculum
```

**See every table's structure at once:**

```
.schema
```

## Reading data

**Everything in a table:**

```sql
SELECT * FROM curriculum;
```

**Specific columns:**

```sql
SELECT id, name FROM topic;
```

**Filter with WHERE:**

```sql
SELECT title, entry_type FROM knowledge_entry WHERE entry_type = 'definition';
```

## JOINs — connecting tables

**Entries with their topic and curriculum:**

```sql
SELECT c.name AS curriculum, t.name AS topic, ke.title, ke.entry_type
FROM knowledge_entry ke
JOIN topic t ON ke.topic_id = t.id
JOIN curriculum c ON t.curriculum_id = c.id;
```

**Which tags are on which entries:**

```sql
SELECT ke.title, tag.name AS tag
FROM knowledge_entry_tag ket
JOIN knowledge_entry ke ON ket.knowledge_entry_id = ke.id
JOIN tag ON ket.tag_id = tag.id;
```

**Related entries (the directed graph):**

```sql
SELECT
    src.title AS source,
    tgt.title AS target,
    r.relationship_type
FROM related_knowledge_entries r
JOIN knowledge_entry src ON r.source_entry_id = src.id
JOIN knowledge_entry tgt ON r.target_entry_id = tgt.id;
```

## Counting and grouping

```sql
SELECT COUNT(*) FROM knowledge_entry;

SELECT entry_type, COUNT(*) AS n
FROM knowledge_entry
GROUP BY entry_type;
```

## Exiting

```
.quit
```

Or press `Ctrl+D`.

## Cheat sheet

| What you want | Command |
|---|---|
| Open a database | `sqlite3 explore.db` |
| List tables | `.tables` |
| See table structure | `.schema tablename` |
| Readable output | `.mode column` then `.headers on` |
| Select rows | `SELECT * FROM tablename;` |
| Filter | `SELECT * FROM t WHERE col = 'val';` |
| Join tables | `SELECT ... FROM a JOIN b ON a.id = b.a_id;` |
| Count rows | `SELECT COUNT(*) FROM tablename;` |
| Exit | `.quit` |
