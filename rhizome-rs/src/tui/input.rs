//! Chat input bar — wraps tui-textarea with submit-on-Enter behavior.
//!
//! The TUI main loop forwards key events here. When Enter is pressed,
//! `take_input()` returns the text and clears the buffer. The visual
//! appearance changes when the agent is busy (dimmed, different placeholder).

use ratatui::style::{Color, Style};
use tui_textarea::TextArea;

/// Create a new TextArea configured for chat input.
pub fn new_input() -> TextArea<'static> {
    let mut ta = TextArea::default();
    ta.set_cursor_line_style(Style::default());
    ta.set_placeholder_text("Type a message...");
    ta.set_block(
        ratatui::widgets::Block::default()
            .borders(ratatui::widgets::Borders::ALL)
            .title(" Input "),
    );
    ta
}

/// Apply visual style indicating the input is disabled (agent is busy).
pub fn set_busy(ta: &mut TextArea<'_>, busy: bool) {
    if busy {
        ta.set_placeholder_text("Agent is thinking...");
        ta.set_block(
            ratatui::widgets::Block::default()
                .borders(ratatui::widgets::Borders::ALL)
                .border_style(Style::default().fg(Color::DarkGray))
                .title(" Input "),
        );
    } else {
        ta.set_placeholder_text("Type a message...");
        ta.set_block(
            ratatui::widgets::Block::default()
                .borders(ratatui::widgets::Borders::ALL)
                .title(" Input "),
        );
    }
}

/// Extract the current text from the input and clear it.
/// Returns `None` if the input is empty/whitespace.
pub fn take_input(ta: &mut TextArea<'_>) -> Option<String> {
    let text: String = ta.lines().join("\n");
    let trimmed = text.trim().to_string();
    if trimmed.is_empty() {
        return None;
    }
    // Clear the textarea
    ta.select_all();
    ta.cut();
    Some(trimmed)
}
