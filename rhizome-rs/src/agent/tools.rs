//! Tool definitions and dispatch for the agent.

use std::collections::{HashMap, VecDeque};

use itertools::Itertools;
use serde::Deserialize;
use sqlx::SqlitePool;

use crate::agent::types::ToolDefinition;
use crate::db::models::{EntryType, Topic};
use crate::db::{entries, topics};

// ### Input structs (for deserializing tool call arguments) ###

#[derive(Deserialize)]
struct ListEntriesInput {
    topic_ids: Vec<i64>,
}

#[derive(Deserialize)]
struct ReadEntriesInput {
    entry_ids: Vec<i64>,
}

#[derive(Deserialize)]
struct CreateTopicInput {
    name: String,
    parent_id: Option<i64>,
    description: Option<String>,
}

#[derive(Deserialize)]
struct CreateEntryInput {
    topic_id: i64,
    title: String,
    content: String,
    entry_type: Option<String>,
}

#[derive(Deserialize)]
struct SearchEntriesInput {
    query: String,
    topic_id: Option<i64>,
}

// ### Tool definitions (JSON schemas sent to the API) ###

pub fn definitions() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "list_topics".into(),
            description: "List the entire topic tree with entry counts. Returns a nested, \
                          indented view of all topics showing [id], name, and how many \
                          knowledge entries each topic contains."
                .into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        },
        ToolDefinition {
            name: "list_entries".into(),
            description: "Show one or more topics' details and list all their knowledge \
                          entries by title and ID. Use read_entries to read full content."
                .into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "topic_ids": {
                        "type": "array",
                        "items": { "type": "integer" },
                        "description": "Topic IDs to list entries for"
                    }
                },
                "required": ["topic_ids"]
            }),
        },
        ToolDefinition {
            name: "read_entries".into(),
            description: "Get the full details of one or more knowledge entries by their IDs."
                .into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "entry_ids": {
                        "type": "array",
                        "items": { "type": "integer" },
                        "description": "Entry IDs to read"
                    }
                },
                "required": ["entry_ids"]
            }),
        },
        ToolDefinition {
            name: "create_topic".into(),
            description: "Create a new topic, optionally under an existing parent topic.".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Topic name"
                    },
                    "parent_id": {
                        "type": "integer",
                        "description": "Optional parent topic ID"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional topic description"
                    }
                },
                "required": ["name"]
            }),
        },
        ToolDefinition {
            name: "create_entry".into(),
            description: "Create a new knowledge entry under a topic.".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "topic_id": {
                        "type": "integer",
                        "description": "Topic ID to create the entry under"
                    },
                    "title": {
                        "type": "string",
                        "description": "Entry title"
                    },
                    "content": {
                        "type": "string",
                        "description": "Entry content"
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["fact", "exposition", "overview"],
                        "description": "Optional entry type"
                    }
                },
                "required": ["topic_id", "title", "content"]
            }),
        },
        ToolDefinition {
            name: "search_entries".into(),
            description: "Search knowledge entries by keyword across title and content. \
                          Optionally scope to a specific topic."
                .into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term"
                    },
                    "topic_id": {
                        "type": "integer",
                        "description": "Optional topic ID to scope the search"
                    }
                },
                "required": ["query"]
            }),
        },
    ]
}

/// Execute a tool call by name and return the result as a string
///
/// Errors are formatted into the string (never panics), because tool results
/// are always sent back to the LLM as text.
pub async fn dispatch(
    pool: &SqlitePool,
    name: &str,
    input: serde_json::Value,
) -> String {
    let result = match name {
        "list_topics" => tool_list_topics(pool).await,
        "list_entries" => match serde_json::from_value::<ListEntriesInput>(input) {
            Ok(p) => tool_list_entries(pool, &p.topic_ids).await,
            Err(e) => Err(e.to_string()),
        },
        "read_entries" => match serde_json::from_value::<ReadEntriesInput>(input) {
            Ok(p) => tool_read_entries(pool, &p.entry_ids).await,
            Err(e) => Err(e.to_string()),
        },
        "create_topic" => match serde_json::from_value::<CreateTopicInput>(input) {
            Ok(p) => tool_create_topic(pool, &p).await,
            Err(e) => Err(e.to_string()),
        },
        "create_entry" => match serde_json::from_value::<CreateEntryInput>(input) {
            Ok(p) => tool_create_entry(pool, &p).await,
            Err(e) => Err(e.to_string()),
        },
        "search_entries" => match serde_json::from_value::<SearchEntriesInput>(input) {
            Ok(p) => tool_search_entries(pool, &p).await,
            Err(e) => Err(e.to_string()),
        },
        other => Err(format!("Unknown tool: {}", other)),
    };

    match result {
        Ok(s) => s,
        Err(e) => format!("Error: {}", e),
    }
}

// ### Tool Implementations ###

async fn tool_list_topics(
    pool: &SqlitePool,
) -> Result<String, String> {
    let all_topics: Vec<Topic> = sqlx::query_as(
        "SELECT * FROM topic ORDER BY id"
    )
    .fetch_all(pool)
    .await
    .map_err(|e| e.to_string())?;

    if all_topics.is_empty() {
        return Ok("No topics found.".into());
    }

    // Get entry counts per topic in one query
    let counts: Vec<(i64, i64)> = sqlx::query_as(
        "SELECT topic_id, COUNT(*) FROM knowledge_entry GROUP BY topic_id"
    )
    .fetch_all(pool)
    .await
    .map_err(|e| e.to_string())?;
    let count_map: HashMap<i64, i64> = counts.into_iter().collect();

    // Build parent_id -> children lookup
    let children_map: HashMap<Option<i64>, Vec<&Topic>> = all_topics.iter()
        .into_group_map_by(|t| t.parent_id);

    // Iterative DFS to build indented output.
    // Each stack item is (topic_id, depth). We push children in reverse
    // so they pop in the correct forward order.
    let mut lines = Vec::new();
    let mut stack: VecDeque<(Option<i64>, usize)> = VecDeque::new();

    // Seed with root-level topics (reversed so first child pops first)
    if let Some(roots) = children_map.get(&None) {
        for t in roots.iter().rev() {
            stack.push_front((Some(t.id), 0));
        }
    }

    while let Some((topic_id, depth)) = stack.pop_front() {
        // Emit line for this node
        if let Some(tid) = topic_id {
            let count = count_map.get(&tid).copied().unwrap_or(0);
            // Find the topic by id (we have all_topics in memory)
            if let Some(t) = all_topics.iter().find(|t| t.id == tid) {
                let indent = "  ".repeat(depth);
                lines.push(format!("{}- [{}] {} ({} entries)", indent, t.id, t.name, count));
            }

            // Push this node's children in reverse so they pop in order
            if let Some(kids) = children_map.get(&Some(tid)) {
                for child in kids.iter().rev() {
                    stack.push_front((Some(child.id), depth + 1));
                }
            }
        }
    }

    Ok(lines.join("\n"))
}

async fn tool_create_topic(
    pool: &SqlitePool,
    input: &CreateTopicInput,
) -> Result<String, String> {
    let topic = topics::create_topic(
        pool,
        &input.name,
        input.parent_id,
        input.description.as_deref(),
    )
    .await
    .map_err(|e| e.to_string())?;

    Ok(format!("Created topic [{}] {}", topic.id, topic.name))
}

async fn tool_list_entries(
    pool: &SqlitePool,
    topic_ids: &[i64],
) -> Result<String, String> {
    let mut sections = Vec::new();

    for &tid in topic_ids {
        let topic = topics::get_topic(pool, tid)
            .await
            .map_err(|e| e.to_string())?;

        let Some(topic) = topic else {
            sections.push(format!("Topic {} not found.", tid));
            continue;
        };

        let entry_list = entries::list_entries(pool, tid)
            .await
            .map_err(|e| e.to_string())?;
        let mut lines = vec![format!("Topic [{}]: {}", topic.id, topic.name)];
        if let Some(ref desc) = topic.description {
            lines.push(format!("Description: {}", desc));
        }
        lines.push(String::new());
        
        if entry_list.is_empty() {
            lines.push("No entries in this topic.".into());
        } else {
            lines.push(format!("{} entries:", entry_list.len()));
            for e in &entry_list {
                let type_str = match &e.entry_type {
                    Some(t) => format!(" ({:?})", t).to_lowercase(),
                    None => String::new(),
                };
                lines.push(format!("  - [{}] {}{}", e.id, e.title, type_str));
            }
        }
        sections.push(lines.join("\n"));
    }

    Ok(sections.join("\n\n---\n\n"))
}

async fn tool_read_entries(
    pool: &SqlitePool,
    entry_ids: &[i64],
) -> Result<String, String> {
    let mut sections = Vec::new();

    for &eid in entry_ids {
        let entry = entries::get_entry(pool, eid)
            .await
            .map_err(|e| e.to_string())?;
        let Some(entry) = entry else {
            sections.push(format!("[{}] Not found.", eid));
            continue;
        };

        let type_name = match &entry.entry_type {
            Some(t) => format!("{:?}", t).to_lowercase(),
            None => "unset".into(),
        };

        let mut lines = vec![
            format!("[{}] {}", entry.id, entry.title),
            format!("Type: {}", type_name),
            format!("Content: {}", entry.content),
        ];
        if !entry.additional_notes.is_empty() {
            lines.push(format!("Notes: {}", entry.additional_notes));
        }
        if let Some(d) = entry.difficulty {
            lines.push(format!("Difficulty: {}", d));
        }
        sections.push(lines.join("\n"));
    }

    Ok(sections.join("\n\n---\n\n"))
}

async fn tool_create_entry(
    pool: &SqlitePool,
    input: &CreateEntryInput,
) -> Result<String, String> {
    let entry_type = input
        .entry_type
        .as_deref()
        .map(|s| match s {
            "fact" => Ok(EntryType::Fact),
            "exposition" => Ok(EntryType::Exposition),
            "overview" => Ok(EntryType::Overview),
            other => Err(format!("Invalid entry_type: {}", other)),
        })
        .transpose()?;

    let entry = entries::create_entry(
        pool,
        input.topic_id,
        &input.title,
        &input.content,
        entry_type,
        None,
        None,
        false,
    )
    .await
    .map_err(|e| e.to_string())?;

    Ok(format!("Created entry [{}] {}", entry.id, entry.title))
}

async fn tool_search_entries(
    pool: &SqlitePool,
    input: &SearchEntriesInput,
) -> Result<String, String> {
    let results = entries::search_entries(pool, &input.query, input.topic_id)
        .await
        .map_err(|e| e.to_string())?;

    if results.is_empty() {
        return Ok(format!("No entries found matching '{}'.", input.query));
    }

    let mut lines = vec![format!("Found {} entries:", results.len())];
    for e in &results {
        lines.push(format!(
            "  - [{}] {} (topic {})",
            e.id, e.title, e.topic_id
        ));
    }
    Ok(lines.join("\n"))
}

