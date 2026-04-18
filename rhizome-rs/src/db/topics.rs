//! CRUD operations for topics

use sqlx::SqlitePool;
use crate::db::models::Topic;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct TopicWithDepth {
    #[sqlx(flatten)]
    pub topic: Topic,
    pub depth: i64,
}

#[derive(Debug, thiserror::Error)]
pub enum TopicError {
    #[error("Topic {0} not found")]
    NotFound(i64),

    // Transparently wraps any sqlx::Error so we can use '?' on queries
    #[error(transparent)]
    Db(#[from] sqlx::Error),
}

// ### Operations ###

pub async fn create_topic(
    pool: &SqlitePool,
    name: &str,
    parent_id: Option<i64>,
    description: Option<&str>,
) -> Result<Topic, TopicError> {
    let topic = sqlx::query_as::<_, Topic>(
        "INSERT INTO topic (name, parent_id, description)
        VALUES (?, ?, ?)
        RETURNING *",
    )
    .bind(name)
    .bind(parent_id)
    .bind(description)
    .fetch_one(pool)
    .await?;

    Ok(topic)
}

pub async fn get_topic(
    pool: &SqlitePool,
    topic_id: i64,
) -> Result<Option<Topic>, TopicError> {
    let topic = sqlx::query_as::<_, Topic>(
        "SELECT * FROM topic WHERE id = ?",
    )
    .bind(topic_id)
    .fetch_optional(pool)
    .await?;

    Ok(topic)
}

pub async fn list_root_topics(
    pool: &SqlitePool,
) -> Result<Vec<Topic>, TopicError> {
    let topic = sqlx::query_as::<_, Topic>(
        "SELECT * FROM topic WHERE parent_id IS NULL",
    )
    .fetch_all(pool)
    .await?;

    Ok(topic)
}

pub async fn list_children(
    pool: &SqlitePool,
    parent_id: i64,
) -> Result<Vec<Topic>, TopicError> {
    let topics = sqlx::query_as::<_, Topic>(
        "SELECT * FROM topic WHERE parent_id = ?",
    )
    .bind(parent_id)
    .fetch_all(pool)
    .await?;

    Ok(topics)
}

pub async fn get_subtree(
    pool: &SqlitePool,
    root_topic_id: i64,
    max_depth: Option<i64>,
) -> Result<Vec<TopicWithDepth>, TopicError> {
    let max_depth = max_depth.unwrap_or(10);
    let rows = sqlx::query_as::<_, TopicWithDepth>(
        "WITH RECURSIVE subtree(topic_id, depth) AS (
            SELECT id, 1
              FROM topic
             WHERE parent_id = ?1
            UNION ALL
            SELECT t.id, subtree.depth + 1
              FROM topic t
              JOIN subtree ON t.parent_id = subtree.topic_id
             WHERE subtree.depth < ?2
        )
        SELECT t.id, t.parent_id, t.name, t.description,
               t.created_at, t.updated_at,
               subtree.depth
          FROM subtree
          JOIN topic t ON t.id = subtree.topic_id
         ORDER BY subtree.depth, t.id"
    )
    .bind(root_topic_id)
    .bind(max_depth)
    .fetch_all(pool)
    .await?;

    Ok(rows)
}

pub async fn update_topic(
    pool: &SqlitePool,
    topic_id: i64,
    name: Option<&str>,
    description: Option<&str>,
) -> Result<Topic, TopicError> {
    let existing = get_topic(pool, topic_id)
        .await?
        .ok_or(TopicError::NotFound(topic_id))?;

    let final_name = name.unwrap_or(&existing.name);
    let final_destination = description.or(existing.description.as_deref());

    let topic = sqlx::query_as::<_, Topic>(
        "UPDATE topic
            SET name = ?, description = ?, updated_at = unixepoch()
          WHERE id = ?
        RETURNING *"
    )
    .bind(final_name)
    .bind(final_destination)
    .bind(topic_id)
    .fetch_one(pool)
    .await?;

    Ok(topic)
}

pub async fn delete_topic(
    pool: &SqlitePool,
    topic_id: i64,
) -> Result<(), TopicError> {
    let result = sqlx::query("DELETE FROM topic WHERE id = ?")
        .bind(topic_id)
        .execute(pool)
        .await?;

    if result.rows_affected() == 0 {
        return Err(TopicError::NotFound(topic_id));
    }

    Ok(())
}

