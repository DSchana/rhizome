//! Per-tab state — each tab is an independent chat session.
//!
//! Mirrors Python's ChatTabPane: each tab has its own message history,
//! mode, agent, scroll position, focus, and input state.

use tokio::sync::mpsc;
use tui_textarea::TextArea;

use crate::tui::focus::FocusTarget;
use crate::tui::input_history::InputHistory;

// ── Session mode ─────────────────────────────────────────────────────

/// The agent interaction mode for a session.
/// Mirrors Python's SessionMode enum.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionMode {
    Idle,
    Learn,
    Review,
}

impl SessionMode {
    /// Cycle to the next mode: Idle → Learn → Review → Idle
    pub fn next(self) -> Self {
        match self {
            Self::Idle => Self::Learn,
            Self::Learn => Self::Review,
            Self::Review => Self::Idle,
        }
    }

    pub fn label(&self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Learn => "learn",
            Self::Review => "review",
        }
    }
}

// ── Tool call state ──────────────────────────────────────────────────

/// State for a single tool call in the display.
#[derive(Debug, Clone)]
pub struct ToolCallState {
    pub name: String,
    pub result: Option<String>,
    pub collapsed: bool,
}

// ── Chat message ─────────────────────────────────────────────────────

/// The role associated with a chat message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChatRole {
    User,
    Assistant,
    ToolCall,
    System,
    Error,
}

/// A single message in the chat history.
#[derive(Debug, Clone)]
pub struct ChatMessage {
    pub role: ChatRole,
    pub content: String,
    pub collapsed: bool,
}

impl ChatMessage {
    pub fn new(role: ChatRole, content: String) -> Self {
        Self {
            role,
            content,
            collapsed: false,
        }
    }
}

// ── Sidebar state ────────────────────────────────────────────────────

/// A node in the topic tree sidebar.
#[derive(Debug, Clone)]
pub struct TreeNode {
    pub id: i64,
    pub name: String,
    pub depth: usize,
    pub expanded: bool,
    pub has_children: bool,
    pub entry_count: i64,
}

/// State for the topic tree sidebar.
#[derive(Debug, Clone)]
pub struct SidebarState {
    pub nodes: Vec<TreeNode>,
    pub cursor: usize,
    pub active_topic_id: Option<i64>,
    pub needs_refresh: bool,
}

impl SidebarState {
    pub fn new() -> Self {
        Self {
            nodes: Vec::new(),
            cursor: 0,
            active_topic_id: None,
            needs_refresh: true,
        }
    }
}

// ── Explorer state ───────────────────────────────────────────────────

/// View mode for the explorer viewer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExplorerViewMode {
    TopicsOnly,
    TopicsAndEntries,
}

impl ExplorerViewMode {
    pub fn next(self) -> Self {
        match self {
            Self::TopicsOnly => Self::TopicsAndEntries,
            Self::TopicsAndEntries => Self::TopicsOnly,
        }
    }
}

/// An entry displayed in the explorer's entry list.
#[derive(Debug, Clone)]
pub struct ExplorerEntry {
    pub id: i64,
    pub title: String,
    pub entry_type: Option<String>,
    pub content: String,
}

/// State for the explorer viewer.
#[derive(Debug, Clone)]
pub struct ExplorerState {
    pub view_mode: ExplorerViewMode,
    pub tree: SidebarState,
    pub entries: Vec<ExplorerEntry>,
    pub entry_cursor: usize,
    /// Which sub-pane has focus: 0 = tree, 1 = entries
    pub active_pane: usize,
}

impl ExplorerState {
    pub fn new() -> Self {
        Self {
            view_mode: ExplorerViewMode::TopicsOnly,
            tree: SidebarState::new(),
            entries: Vec::new(),
            entry_cursor: 0,
            active_pane: 0,
        }
    }
}

// ── Command palette state ────────────────────────────────────────────

/// State for the command palette popup.
#[derive(Debug, Clone)]
pub struct PaletteState {
    pub filter: String,
    pub selected: usize,
    pub visible: bool,
}

impl PaletteState {
    pub fn new() -> Self {
        Self {
            filter: String::new(),
            selected: 0,
            visible: false,
        }
    }
}

// ── Interrupt state ──────────────────────────────────────────────────

/// An active interrupt prompt from the agent.
#[derive(Debug, Clone)]
pub enum InterruptKind {
    Choices {
        prompt: String,
        options: Vec<String>,
        cursor: usize,
    },
    Warning {
        message: String,
        options: Vec<String>,
        cursor: usize,
    },
}

// ── Tab state ────────────────────────────────────────────────────────

/// All state for a single tab / chat session.
pub struct TabState {
    pub name: String,
    pub messages: Vec<ChatMessage>,
    pub mode: SessionMode,
    pub focus: FocusTarget,
    pub input: TextArea<'static>,
    pub history: InputHistory,
    pub is_busy: bool,
    pub scroll_offset: u16,
    pub spinner_frame: u8,

    // Tool call tracking for the current turn
    pub tool_calls: Vec<ToolCallState>,

    // Sidebar
    pub sidebar_visible: bool,
    pub sidebar: SidebarState,

    // Explorer
    pub explorer: Option<ExplorerState>,

    // Command palette
    pub palette: PaletteState,

    // Interrupt
    pub interrupt: Option<InterruptKind>,

    // Channel to send user text to this tab's agent task
    pub cmd_tx: mpsc::Sender<String>,
}

impl TabState {
    pub fn new(name: String, cmd_tx: mpsc::Sender<String>) -> Self {
        let input = crate::tui::input::new_input();

        Self {
            name,
            messages: vec![ChatMessage::new(
                ChatRole::System,
                "Rhizome — type a message to chat.".into(),
            )],
            mode: SessionMode::Idle,
            focus: FocusTarget::default_focus(),
            input,
            history: InputHistory::new(100),
            is_busy: false,
            scroll_offset: 0,
            spinner_frame: 0,
            tool_calls: Vec::new(),
            sidebar_visible: false,
            sidebar: SidebarState::new(),
            explorer: None,
            palette: PaletteState::new(),
            interrupt: None,
            cmd_tx,
        }
    }
}
