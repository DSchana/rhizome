//! Input bar drawing helpers.
//!
//! The TextArea widget renders itself — this module provides the
//! factory, busy styling, and text extraction helpers.

use ratatui::{
    style::{Color, Style},
    widgets::{Block, Borders},
};
use tui_textarea::TextArea;

use crate::tui::theme;

/// Create a new TextArea configured for chat input.
pub fn new_input() -> TextArea<'static> {
    let mut ta = TextArea::default();
    ta.set_cursor_line_style(Style::default());
    ta.set_placeholder_text("Type a message...");
    ta.set_block(input_block(false, false));
    ta
}

/// Apply visual style for busy/command states.
pub fn set_busy(ta: &mut TextArea<'_>, busy: bool) {
    if busy {
        ta.set_placeholder_text("Agent is thinking...");
        ta.set_block(input_block(true, false));
    } else {
        ta.set_placeholder_text("Type a message...");
        ta.set_block(input_block(false, false));
    }
}

/// Apply shell-mode border (red) when input starts with `!`.
pub fn set_shell_mode(ta: &mut TextArea<'_>, is_shell: bool) {
    if is_shell {
        ta.set_block(input_block(false, true));
    } else {
        ta.set_block(input_block(false, false));
    }
}

/// Extract the current text and clear the input.
pub fn take_input(ta: &mut TextArea<'_>) -> Option<String> {
    let text: String = ta.lines().join("\n");
    let trimmed = text.trim().to_string();
    if trimmed.is_empty() {
        return None;
    }
    ta.select_all();
    ta.cut();
    Some(trimmed)
}

/// Set the text content of the textarea (for history navigation).
pub fn set_text(ta: &mut TextArea<'_>, text: &str) {
    ta.select_all();
    ta.cut();
    ta.insert_str(text);
}

fn input_block(busy: bool, shell: bool) -> Block<'static> {
    let border_color = if shell {
        Color::Red
    } else if busy {
        theme::DIM_COLOR
    } else {
        theme::BORDER_COLOR
    };

    let title = if shell { " Shell " } else { " Input " };

    Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(border_color))
        .title(title)
}
