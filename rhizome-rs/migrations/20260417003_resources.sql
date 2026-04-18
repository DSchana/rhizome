-- Resources, sections, chunks

CREATE TABLE resource (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL,
    content_hash       TEXT,
    summary            TEXT,
    estimated_tokens   INTEGER,
    source_type        TEXT,
    loading_preference TEXT    NOT NULL DEFAULT 'auto'
                       CHECK(loading_preference IN ('auto', 'context_stuff', 'vector_store')),
    created_at         INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at         INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE resource_content (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id     INTEGER NOT NULL UNIQUE REFERENCES resource(id) ON DELETE CASCADE,
    raw_text        TEXT,
    source_bytes    BLOB,
    source_metadata TEXT    -- JSON stored as text
);
CREATE TABLE topic_resource (
    topic_id    INTEGER NOT NULL REFERENCES topic(id)    ON DELETE CASCADE,
    resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, resource_id)
);
CREATE TABLE resource_section (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id  INTEGER NOT NULL REFERENCES resource(id)         ON DELETE CASCADE,
    parent_id    INTEGER REFERENCES resource_section(id)          ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    depth        INTEGER NOT NULL,
    position     INTEGER NOT NULL,
    page_start   INTEGER,
    page_end     INTEGER,
    start_offset INTEGER,
    UNIQUE(resource_id, position)
);
CREATE INDEX ix_resource_section_resource_id ON resource_section(resource_id);
CREATE INDEX ix_resource_section_parent_id   ON resource_section(parent_id);
CREATE TABLE resource_chunk (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id  INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset   INTEGER NOT NULL,
    context_tag  TEXT,   -- JSON stored as text
    embedding    BLOB
);
CREATE INDEX ix_resource_chunk_resource_id ON resource_chunk(resource_id);
CREATE TABLE resource_chunk_section (
    chunk_id   INTEGER NOT NULL REFERENCES resource_chunk(id)   ON DELETE CASCADE,
    section_id INTEGER NOT NULL REFERENCES resource_section(id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, section_id)
);

