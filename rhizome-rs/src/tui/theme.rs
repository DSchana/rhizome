//! Shared color constants and style helpers.
//!
//! Centralizes all TUI styling so draw modules don't hardcode colors.

use ratatui::style::{Color, Modifier, Style};

// ── Role colors ──────────────────────────────────────────────────────

pub const USER_COLOR: Color = Color::Cyan;
pub const ASSISTANT_COLOR: Color = Color::White;
pub const TOOL_COLOR: Color = Color::Yellow;
pub const SYSTEM_COLOR: Color = Color::DarkGray;
pub const ERROR_COLOR: Color = Color::Red;

// ── Mode colors ──────────────────────────────────────────────────────

pub const IDLE_COLOR: Color = Color::Green;
pub const LEARN_COLOR: Color = Color::Blue;
pub const REVIEW_COLOR: Color = Color::Magenta;

// ── UI element colors ────────────────────────────────────────────────

pub const BORDER_COLOR: Color = Color::DarkGray;
pub const BORDER_FOCUSED: Color = Color::White;
pub const ACTIVE_TOPIC_COLOR: Color = Color::LightCyan;
pub const CURSOR_COLOR: Color = Color::Green;
pub const DIM_COLOR: Color = Color::DarkGray;
pub const HIGHLIGHT_BG: Color = Color::DarkGray;

// Tab bar
pub const TAB_ACTIVE_BG: Color = Color::DarkGray;
pub const TAB_INACTIVE_FG: Color = Color::Gray;

// Command palette
pub const PALETTE_SELECTED_BG: Color = Color::Blue;
pub const PALETTE_BG: Color = Color::Black;

// ── Style constructors ───────────────────────────────────────────────

pub fn bold(color: Color) -> Style {
    Style::default().fg(color).add_modifier(Modifier::BOLD)
}

pub fn dim(color: Color) -> Style {
    Style::default().fg(color).add_modifier(Modifier::DIM)
}

pub fn style(color: Color) -> Style {
    Style::default().fg(color)
}

pub fn inverted(fg: Color, bg: Color) -> Style {
    Style::default().fg(fg).bg(bg).add_modifier(Modifier::BOLD)
}
