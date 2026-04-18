//! Relation edge management with cycle detection and dependency chain queries

use sqlx::SqlitePool;
use crate::db::models::{KnowledgeEntry, RelatedKnowledgeEntries};

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct EntryWithDepth {
    #[sqlx(flatten)]
    pub entry: KnowledgeEntry,
    pub depth: i64,
}

#[derive(Debug, thiserror::Error)]
pub enum RelationError {
    #[error("Adding {from} -> {to} would create a cycle")]
    CycleDetected { from: i64, to: i64 },

    #[error("Relation {from} -> {to} not found")]
    NotFound { from: i64, to: i64 },
    
    #[error(transparent)]
    Db(#[from] sqlx::Error),
}

/// Check whether adding source->target would create a cycle.
/// Walks forward from target; if it can reach source, a cycle exists.
async fn would_create_cycle(
    pool: &SqlitePool,
    source_entry_id: i64,
    target_entry_id: i64,
) -> Result<bool, sqlx::Error> {
    let row: Option<(i64,)> = sqlx::query_as(
        "WITH RECURSIVE reachable(entry_id) AS (
             SELECT ?1
             UNION
             SELECT r.target_entry_id
               FROM related_knowledge_entries r
               JOIN reachable ON r.source_entry_id = reachable.entry_id
         )
         SELECT 1 FROM reachable WHERE entry_id = ?2 LIMIT 1",
    )
    .bind(target_entry_id)
    .bind(source_entry_id)
    .fetch_optional(pool)
    .await?;
    Ok(row.is_some())
}

pub async fn add_relation(
    pool: &SqlitePool,
    source_entry_id: i64,
    target_entry_id: i64,
    relationship_type: &str,
) -> Result<RelatedKnowledgeEntries, RelationError> {
    if would_create_cycle(pool, source_entry_id, target_entry_id).await? {
        return Err(RelationError::CycleDetected {
            from: source_entry_id,
            to: target_entry_id,
        });
    }
    let relation = sqlx::query_as::<_, RelatedKnowledgeEntries>(
        "INSERT INTO related_knowledge_entries
             (source_entry_id, target_entry_id, relationship_type)
         VALUES (?, ?, ?)
         RETURNING *",
    )
    .bind(source_entry_id)
    .bind(target_entry_id)
    .bind(relationship_type)
    .fetch_one(pool)
    .await?;
    Ok(relation)
}

pub async fn remove_relation(
    pool: &SqlitePool,
    source_entry_id: i64,
    target_entry_id: i64,
) -> Result<(), RelationError> {
    let result = sqlx::query(
        "DELETE FROM related_knowledge_entries
          WHERE source_entry_id = ? AND target_entry_id = ?",
    )
    .bind(source_entry_id)
    .bind(target_entry_id)
    .execute(pool)
    .await?;
    if result.rows_affected() == 0 {
        return Err(RelationError::NotFound {
            from: source_entry_id,
            to: target_entry_id,
        });
    }
    Ok(())
}

/// Return all outgoing relation edges for an entry (one level deep).
pub async fn get_related_entries(
    pool: &SqlitePool,
    entry_id: i64,
) -> Result<Vec<RelatedKnowledgeEntries>, RelationError> {
    let relations = sqlx::query_as::<_, RelatedKnowledgeEntries>(
        "SELECT * FROM related_knowledge_entries
          WHERE source_entry_id = ?",
    )
    .bind(entry_id)
    .fetch_all(pool)
    .await?;
    Ok(relations)
}

