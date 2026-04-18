use chrono::{ DateTime, Utc };
use serde::{ Deserialize, Serialize };
use sqlx::FromRow;

// ### Enums ###

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::Type, PartialEq)]
#[sqlx(rename_all = "lowercase")]
pub enum EntryType {
    Fact,
    Exposition,
    Overview,
}

// ### Core Models ###

#[derive(Debug, Clone, FromRow)]
pub struct Topic {
    pub id: i64,
    pub parent_id: Option<i64>,
    pub name: String,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, FromRow)]
pub struct KnowledgeEntry {
    pub id: i64,
    pub topic_id: i64,
    pub title: String,
    pub content: String,
    pub additional_notes: String,
    pub entry_type: Option<EntryType>,
    pub difficulty: Option<i64>,
    pub speed_testable: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, FromRow)]
pub struct Tag {
    pub id: i64,
    pub name: String,
}

#[derive(Debug, Clone, FromRow)]
pub struct KnowledgeEntryTag {
    pub knowledge_entry_id: i64,
    pub tag_id: i64,
}

#[derive(Debug, Clone, FromRow)]
pub struct RelatedKnowledgeEntries {
    pub source_entry_id: i64,
    pub target_entry_id: i64,
    pub relationship_type: String,
}

