mod agent;
mod config;
mod db;

use std::io::{self, BufRead, Write};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let api_key = config::get_anthropic_api_key()?;
    let db_path = config::get_db_path();

    let pool = db::init_db(&db_path).await?;
    let mut agent = agent::Agent::new(api_key, pool);

    println!("Rhizome — type a message, Ctrl+D to quit.\n");

    let stdin = io::stdin();
    loop {
        print!("> ");
        io::stdout().flush()?;

        let mut line = String::new();
        // read_line returns 0 bytes on EOF (Ctrl+D)
        if stdin.lock().read_line(&mut line)? == 0 {
            break;
        }

        let input = line.trim();
        if input.is_empty() {
            continue;
        }

        if let Err(e) = agent.run_turn(input).await {
            eprintln!("\nError: {e}");
        }

        println!(); // blank line between turns
    }

    Ok(())
}
