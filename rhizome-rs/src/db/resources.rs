//! Resource CRUD operations.

use sqlx::SqlitePool;

use super::models::Resource;

/// List all resources, ordered by name.
pub async fn list_resources(pool: &SqlitePool) -> Result<Vec<Resource>, sqlx::Error> {
    sqlx::query_as::<_, Resource>("SELECT * FROM resource ORDER BY name")
        .fetch_all(pool)
        .await
}

/// List resources linked to a specific topic via the topic_resource junction table.
pub async fn list_resources_for_topic(
    pool: &SqlitePool,
    topic_id: i64,
) -> Result<Vec<Resource>, sqlx::Error> {
    sqlx::query_as::<_, Resource>(
        "SELECT r.* FROM resource r \
         JOIN topic_resource tr ON tr.resource_id = r.id \
         WHERE tr.topic_id = ? \
         ORDER BY r.name",
    )
    .bind(topic_id)
    .fetch_all(pool)
    .await
}
