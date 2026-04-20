//! Focus management — tracks which UI element receives key events.
//!
//! Simple enum-based approach: one active focus target per tab.
//! Key events are routed to the focused element's handler.

/// Which UI element currently has focus in a tab.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusTarget {
    /// The chat input bar (default)
    Input,
    /// The scrollable chat message area
    ChatArea,
    /// The topic tree sidebar
    Sidebar,
    /// The explorer viewer (topics + entries browser)
    Explorer,
    /// The command palette popup
    CommandPalette,
    /// An active interrupt prompt (choices, warning, etc.)
    Interrupt,
}

impl FocusTarget {
    /// The default focus target for a new tab.
    pub fn default_focus() -> Self {
        Self::Input
    }

    /// Whether this focus target is a modal overlay (captures all keys).
    pub fn is_modal(&self) -> bool {
        matches!(self, Self::CommandPalette | Self::Interrupt)
    }
}
