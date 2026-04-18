-- Core tables: topic tree, knowledge entried, tags, relations

CREATE TABLE topic (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER REFERENCES topic(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    description TEXT,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(parent_id, name)
);
CREATE INDEX ix_topic_parent_id ON topic(parent_id);
CREATE TABLE knowledge_entry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id         INTEGER NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    title            TEXT    NOT NULL,
    content          TEXT    NOT NULL,
    additional_notes TEXT    NOT NULL DEFAULT '',
    entry_type       TEXT    CHECK(entry_type IN ('fact', 'exposition', 'overview')),
    difficulty       INTEGER,
    speed_testable   INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at       INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX ix_knowledge_entry_topic_id ON knowledge_entry(topic_id);
CREATE TABLE tag (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE knowledge_entry_tag (
    knowledge_entry_id INTEGER NOT NULL REFERENCES knowledge_entry(id) ON DELETE CASCADE,
    tag_id             INTEGER NOT NULL REFERENCES tag(id)             ON DELETE CASCADE,
    PRIMARY KEY (knowledge_entry_id, tag_id)
);
CREATE TABLE related_knowledge_entries (
    source_entry_id   INTEGER NOT NULL REFERENCES knowledge_entry(id) ON DELETE CASCADE,
    target_entry_id   INTEGER NOT NULL REFERENCES knowledge_entry(id) ON DELETE CASCADE,
    relationship_type TEXT    NOT NULL,
    PRIMARY KEY (source_entry_id, target_entry_id),
    CHECK(source_entry_id != target_entry_id)
);

