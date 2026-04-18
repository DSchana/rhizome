-- Review sessions, flashcards, interactions

CREATE TABLE review_session (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ephemeral         INTEGER NOT NULL DEFAULT 0,
    created_at        INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at        INTEGER NOT NULL DEFAULT (unixepoch()),
    completed_at      TEXT,
    additional_args   TEXT,   -- JSON stored as text
    user_instructions TEXT,
    plan              TEXT,
    final_summary     TEXT
);
CREATE TABLE review_session_topic (
    session_id INTEGER NOT NULL REFERENCES review_session(id) ON DELETE CASCADE,
    topic_id   INTEGER NOT NULL REFERENCES topic(id)          ON DELETE CASCADE,
    PRIMARY KEY (session_id, topic_id),
    UNIQUE(session_id, topic_id)
);
CREATE TABLE review_session_entry (
    session_id INTEGER NOT NULL REFERENCES review_session(id)    ON DELETE CASCADE,
    entry_id   INTEGER NOT NULL REFERENCES knowledge_entry(id)   ON DELETE CASCADE,
    PRIMARY KEY (session_id, entry_id),
    UNIQUE(session_id, entry_id)
);
CREATE TABLE flashcard (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER REFERENCES review_session(id) ON DELETE SET NULL,
    topic_id       INTEGER NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    question_text  TEXT NOT NULL,
    answer_text    TEXT NOT NULL,
    testing_notes  TEXT
);
CREATE INDEX ix_flashcard_session_id ON flashcard(session_id);
CREATE INDEX ix_flashcard_topic_id   ON flashcard(topic_id);
CREATE TABLE flashcard_entry (
    flashcard_id INTEGER NOT NULL REFERENCES flashcard(id)        ON DELETE CASCADE,
    entry_id     INTEGER NOT NULL REFERENCES knowledge_entry(id)  ON DELETE CASCADE,
    PRIMARY KEY (flashcard_id, entry_id),
    UNIQUE(flashcard_id, entry_id)
);
CREATE TABLE review_interaction (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES review_session(id) ON DELETE CASCADE,
    flashcard_id INTEGER REFERENCES flashcard(id) ON DELETE SET NULL,
    summary      TEXT,
    score        INTEGER CHECK(score >= 0 AND score <= 3),
    position     INTEGER NOT NULL
);
CREATE INDEX ix_review_interaction_session_id   ON review_interaction(session_id);
CREATE INDEX ix_review_interaction_flashcard_id ON review_interaction(flashcard_id);
CREATE TABLE review_interaction_entry (
    interaction_id INTEGER NOT NULL REFERENCES review_interaction(id) ON DELETE CASCADE,
    entry_id       INTEGER NOT NULL REFERENCES knowledge_entry(id)    ON DELETE CASCADE,
    PRIMARY KEY (interaction_id, entry_id),
    UNIQUE(interaction_id, entry_id)
);
