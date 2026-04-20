//! Queries for the explorer panel — topics with entry counts and entries.

use sqlx::SqlitePool;

/// A topic with its entry count, for the explorer tree.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct TopicWithCount {
    pub id: i64,
    pub parent_id: Option<i64>,
    pub name: String,
    pub entry_count: i64,
}

/// A minimal entry row for the explorer listing.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct EntryRow {
    pub id: i64,
    pub topic_id: i64,
    pub title: String,
    pub entry_type: Option<String>,
}

/// Load all topics with entry counts + all entries, ordered for tree display.
pub async fn load_explorer_data(
    pool: &SqlitePool,
) -> Result<(Vec<TopicWithCount>, Vec<EntryRow>), sqlx::Error> {
    let topics = sqlx::query_as::<_, TopicWithCount>(
        "SELECT t.id, t.parent_id, t.name,
                (SELECT COUNT(*) FROM knowledge_entry e WHERE e.topic_id = t.id) AS entry_count
           FROM topic t
          ORDER BY t.name",
    )
    .fetch_all(pool)
    .await?;

    let entries = sqlx::query_as::<_, EntryRow>(
        "SELECT id, topic_id, title, entry_type
           FROM knowledge_entry
          ORDER BY topic_id, created_at",
    )
    .fetch_all(pool)
    .await?;

    Ok((topics, entries))
}
