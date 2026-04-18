//! Database layer: pool initialization, migration, and module re-exports

use sqlx::sqlite::{ SqliteConnectOptions, SqlitePoolOptions };
use sqlx::SqlitePool;
use std::str::FromStr;

// Submodule declarations
pub mod entries;
pub mod models;
pub mod relations;
pub mod tags;
pub mod topics;

// Pool initialization
pub async fn init_db(db_path: &str) -> Result<SqlitePool, sqlx::Error> {
    // Build connection
    let options = SqliteConnectOptions::from_str(
        &format!("sqlite://{}?mode=rwc", db_path),
    )?
    .pragma("foreign_keys", "ON")
    .create_if_missing(true);

    // Create the pool
    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await?;

    // Run migrations
    sqlx::migrate!("./migrations")
        .run(&pool)
        .await?;

    Ok(pool)
}

