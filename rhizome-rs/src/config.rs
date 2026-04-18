//! API key and db path resolution

use std::fs;

/// Try to read a string field from ~/.config/rhizome/credentials.json
fn read_config_field(field: &str) -> Option<String> {
    let path = dirs::config_dir()?.join("rhizome").join("credentials.json");
    let text = fs::read_to_string(path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&text).ok()?;
    let value = json.get(field)?.as_str()?;
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

/// Resolve Anthropic API key from
/// `~/.config/rhizome/credentials.json` -> `"anthropic_api_key"`
pub fn get_anthropic_api_key() -> anyhow::Result<String> {
    read_config_field("anthropic_api_key").ok_or_else(|| {
        anyhow::anyhow!(
            "No Anthropic API key found. \
             Add \"anthropic_api_key\" to ~/.config/rhizome/credentials.json"
        )
    })
}

/// Resolve DB path from
/// `~/.config/rhizome/credentials.json` -> `"db_path"`
///
/// Falls back to "rhizome.db" in the current directory if not configured.
pub fn get_db_path() -> String {
    read_config_field("db_path").unwrap_or_else(|| "rhizome.db".to_string())
}
