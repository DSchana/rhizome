//! CRUD + Search operations for knowledge entries

use sqlx::SqlitePool;
use crate::db::models::{ EntryType, KnowledgeEntry };

#[derive(Debug, thiserror::Error)]
pub enum EntryError {
    #[error("KnowledgeEntry {0} not found")]
    NotFound(i64),

    #[error(transparent)]
    Db(#[from] sqlx::Error),
}

pub async fn create_entry(
    pool: &SqlitePool,
    topic_id: i64,
    title: &str,
    content: &str,
    entry_type: Option<EntryType>,
    additional_notes: Option<&str>,
    difficulty: Option<i64>,
    speed_testable: bool,
) -> Result<KnowledgeEntry, EntryError> {
    let notes = additional_notes.unwrap_or("");
    let entry = sqlx::query_as::<_, KnowledgeEntry>(
        "INSERT INTO knowledge_entry
             (topic_id, title, content, additional_notes,
              entry_type, difficulty, speed_testable)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         RETURNING *",
    )
    .bind(topic_id)
    .bind(title)
    .bind(content)
    .bind(notes)
    .bind(entry_type)
    .bind(difficulty)
    .bind(speed_testable)
    .fetch_one(pool)
    .await?;
    Ok(entry)
}

pub async fn get_entry(
    pool: &SqlitePool,
    entry_id: i64,
) -> Result<Option<KnowledgeEntry>, EntryError> {
    let entry = sqlx::query_as::<_, KnowledgeEntry>(
        "SELECT * FROM knowledge_entry WHERE id = ?",
    )
    .bind(entry_id)
    .fetch_optional(pool)
    .await?;
    Ok(entry)
}

pub async fn count_entries(
    pool: &SqlitePool,
    topic_id: i64,
) -> Result<i64, EntryError> {
    let row: (i64,) = sqlx::query_as(
        "SELECT COUNT(*) FROM knowledge_entry WHERE topic_id = ?",
    )
    .bind(topic_id)
    .fetch_one(pool)
    .await?;
    Ok(row.0)
}

pub async fn list_entries(
    pool: &SqlitePool,
    topic_id: i64,
) -> Result<Vec<KnowledgeEntry>, EntryError> {
    let entries = sqlx::query_as::<_, KnowledgeEntry>(
        "SELECT * FROM knowledge_entry
          WHERE topic_id = ?
          ORDER BY created_at",
    )
    .bind(topic_id)
    .fetch_all(pool)
    .await?;
    Ok(entries)
}

pub async fn update_entry(
    pool: &SqlitePool,
    entry_id: i64,
    title: Option<&str>,
    content: Option<&str>,
    entry_type: Option<EntryType>,
    additional_notes: Option<&str>,
    difficulty: Option<i64>,
    speed_testable: Option<bool>,
) -> Result<KnowledgeEntry, EntryError> {
    let existing = get_entry(pool, entry_id)
        .await?
        .ok_or(EntryError::NotFound(entry_id))?;
    let final_title = title.unwrap_or(&existing.title);
    let final_content = content.unwrap_or(&existing.content);
    let final_entry_type = entry_type.or(existing.entry_type);
    let final_notes = additional_notes.unwrap_or(&existing.additional_notes);
    let final_difficulty = difficulty.or(existing.difficulty);
    let final_speed_testable = speed_testable.unwrap_or(existing.speed_testable);
    let entry = sqlx::query_as::<_, KnowledgeEntry>(
        "UPDATE knowledge_entry
            SET title = ?, content = ?, entry_type = ?,
                additional_notes = ?, difficulty = ?,
                speed_testable = ?, updated_at = unixepoch()
          WHERE id = ?
         RETURNING *",
    )
    .bind(final_title)
    .bind(final_content)
    .bind(final_entry_type)
    .bind(final_notes)
    .bind(final_difficulty)
    .bind(final_speed_testable)
    .bind(entry_id)
    .fetch_one(pool)
    .await?;
    Ok(entry)
}

pub async fn delete_entry(
    pool: &SqlitePool,
    entry_id: i64,
) -> Result<(), EntryError> {
    let result = sqlx::query("DELETE FROM knowledge_entry WHERE id = ?")
        .bind(entry_id)
        .execute(pool)
        .await?;
    if result.rows_affected() == 0 {
        return Err(EntryError::NotFound(entry_id));
    }
    Ok(())
}

pub async fn search_entries(
    pool: &SqlitePool,
    query: &str,
    topic_id: Option<i64>,
) -> Result<Vec<KnowledgeEntry>, EntryError> {
    let pattern = format!("%{}%", query);
    let entries = sqlx::query_as::<_, KnowledgeEntry>(
        "SELECT * FROM knowledge_entry
          WHERE (title LIKE ?1 OR content LIKE ?1)
            AND (?2 IS NULL OR topic_id = ?2)",
    )
    .bind(&pattern)
    .bind(topic_id)
    .fetch_all(pool)
    .await?;
    Ok(entries)
}

