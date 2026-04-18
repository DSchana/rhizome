//! Tag CRUD and entry tagging/untagging operations

use sqlx::SqlitePool;
use crate::db::models::{KnowledgeEntry, Tag};

#[derive(Debug, thiserror::Error)]
pub enum TagError {
    #[error(transparent)]
    Db(#[from] sqlx::Error),
}

pub async fn create_tag(
    pool: &SqlitePool,
    name: &str,
) -> Result<Tag, TagError> {
    let normalized = name.to_lowercase();
    let tag = sqlx::query_as::<_, Tag>(
        "INSERT INTO tag (name) VALUES (?) RETURNING *",
    )
    .bind(&normalized)
    .fetch_one(pool)
    .await?;
    Ok(tag)
}

pub async fn list_tags(
    pool: &SqlitePool,
) -> Result<Vec<Tag>, TagError> {
    let tags = sqlx::query_as::<_, Tag>(
        "SELECT * FROM tag",
    )
    .fetch_all(pool)
    .await?;
    Ok(tags)
}

/// Tag an entry. Creates the tag if it doesn't exist. Idempotent.
///
/// Uses INSERT OR IGNORE to avoid the TOCTOU race the Python version has.
pub async fn tag_entry(
    pool: &SqlitePool,
    entry_id: i64,
    tag_name: &str,
) -> Result<(), TagError> {
    let normalized = tag_name.to_lowercase();
    // Get-or-create the tag atomically
    sqlx::query(
        "INSERT OR IGNORE INTO tag (name) VALUES (?)",
    )
    .bind(&normalized)
    .execute(pool)
    .await?;
    let tag = sqlx::query_as::<_, Tag>(
        "SELECT * FROM tag WHERE name = ?",
    )
    .bind(&normalized)
    .fetch_one(pool)
    .await?;
    // Insert the association, no-op if already exists
    sqlx::query(
        "INSERT OR IGNORE INTO knowledge_entry_tag
             (knowledge_entry_id, tag_id)
         VALUES (?, ?)",
    )
    .bind(entry_id)
    .bind(tag.id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Remove a tag from an entry. No-op if the tag or association doesn't exist.
pub async fn untag_entry(
    pool: &SqlitePool,
    entry_id: i64,
    tag_name: &str,
) -> Result<(), TagError> {
    let normalized = tag_name.to_lowercase();
    // Single query: deletes the row if both the tag and association exist,
    // otherwise affects 0 rows (no-op). No error either way.
    sqlx::query(
        "DELETE FROM knowledge_entry_tag
          WHERE knowledge_entry_id = ?
            AND tag_id = (SELECT id FROM tag WHERE name = ?)",
    )
    .bind(entry_id)
    .bind(&normalized)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn get_entries_by_tag(
    pool: &SqlitePool,
    tag_name: &str,
) -> Result<Vec<KnowledgeEntry>, TagError> {
    let normalized = tag_name.to_lowercase();
    let entries = sqlx::query_as::<_, KnowledgeEntry>(
        "SELECT ke.*
           FROM knowledge_entry ke
           JOIN knowledge_entry_tag ket ON ke.id = ket.knowledge_entry_id
           JOIN tag t ON ket.tag_id = t.id
          WHERE t.name = ?",
    )
    .bind(&normalized)
    .fetch_all(pool)
    .await?;
    Ok(entries)
}

