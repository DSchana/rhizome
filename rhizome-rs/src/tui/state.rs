//! Centralized TUI application state.

use sqlx::SqlitePool;
use tui_textarea::TextArea;

use super::chat::{ChatMessage, ChatRole};
use super::input;
use super::status::StatusInfo;

/// Which widget currently owns keyboard focus.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Input,
    CommandPalette,
    Explorer,
}

/// State for the command palette overlay.
pub struct CommandPaletteState {
    pub visible: bool,
    pub filter: String,
    pub selected_index: usize,
}

/// A row in the explorer panel — either a topic header or an entry under a topic.
#[derive(Debug, Clone)]
pub enum ExplorerRow {
    Topic {
        id: i64,
        name: String,
        depth: usize,
        entry_count: i64,
    },
    Entry {
        id: i64,
        title: String,
        entry_type: Option<String>,
        depth: usize,
    },
}

/// State for the explorer panel (topics + entries).
pub struct ExplorerState {
    pub rows: Vec<ExplorerRow>,
    pub cursor: usize,
}

/// All mutable state for the TUI application.
pub struct AppState {
    pub messages: Vec<ChatMessage>,
    pub text_input: TextArea<'static>,
    pub is_busy: bool,
    pub should_quit: bool,
    pub scroll_offset: u16,
    pub focus: Focus,
    pub status: StatusInfo,
    pub palette: CommandPaletteState,
    pub explorer: ExplorerState,
    pub explorer_visible: bool,
    pub pool: SqlitePool,
}

impl AppState {
    pub fn new(pool: SqlitePool) -> Self {
        let mut messages = Vec::new();
        messages.push(ChatMessage {
            role: ChatRole::System,
            content: "Rhizome — type a message to chat. Ctrl+C to quit.".into(),
        });

        Self {
            messages,
            text_input: input::new_input(),
            is_busy: false,
            should_quit: false,
            scroll_offset: 0,
            focus: Focus::Input,
            status: StatusInfo::default(),
            palette: CommandPaletteState {
                visible: false,
                filter: String::new(),
                selected_index: 0,
            },
            explorer: ExplorerState {
                rows: Vec::new(),
                cursor: 0,
            },
            explorer_visible: false,
            pool,
        }
    }
}
