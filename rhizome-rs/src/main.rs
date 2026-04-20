mod agent;
mod config;
mod db;
mod tui;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let api_key = config::get_anthropic_api_key()?;
    let db_path = config::get_db_path();

    let pool = db::init_db(&db_path).await?;

    tui::run(api_key, pool).await?;

    Ok(())
}
