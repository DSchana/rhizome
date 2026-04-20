//! Chat message area — renders scrollable message history with rich formatting.
//!
//! User messages get a cyan left border, assistant messages get white,
//! tool calls show as yellow tree lines, system messages are dim.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget, Wrap},
};

use crate::tui::tab::{ChatMessage, ChatRole};
use crate::tui::theme;

/// Collapse threshold: messages longer than this many lines get a collapse hint.
const COLLAPSE_LINE_THRESHOLD: usize = 8;

/// Convert messages into styled Lines for rendering.
pub fn render_messages(messages: &[ChatMessage], _width: u16) -> Vec<Line<'static>> {
    let mut lines: Vec<Line<'static>> = Vec::new();

    for msg in messages {
        let (prefix, prefix_style, content_style, border_char) = match msg.role {
            ChatRole::User => (
                "you: ",
                theme::bold(theme::USER_COLOR),
                theme::style(theme::USER_COLOR),
                "│ ",
            ),
            ChatRole::Assistant => (
                "",
                Style::default(),
                theme::style(theme::ASSISTANT_COLOR),
                "│ ",
            ),
            ChatRole::ToolCall => ("", Style::default(), theme::style(theme::TOOL_COLOR), "  "),
            ChatRole::System => ("", Style::default(), theme::dim(theme::SYSTEM_COLOR), "  "),
            ChatRole::Error => (
                "error: ",
                theme::bold(theme::ERROR_COLOR),
                theme::style(theme::ERROR_COLOR),
                "  ",
            ),
        };

        let border_style = match msg.role {
            ChatRole::User => theme::style(theme::USER_COLOR),
            ChatRole::Assistant => theme::dim(theme::ASSISTANT_COLOR),
            _ => theme::style(theme::DIM_COLOR),
        };

        // Handle collapse
        let content = &msg.content;
        let hard_lines: Vec<&str> = content.split('\n').collect();
        let total_hard_lines = hard_lines.len();
        let show_collapse_hint = msg.role == ChatRole::Assistant
            && total_hard_lines > COLLAPSE_LINE_THRESHOLD
            && msg.collapsed;

        let display_lines: Vec<&str> = if show_collapse_hint {
            let mut truncated: Vec<&str> = hard_lines[..3].to_vec();
            truncated.push(""); // blank line before hint
            truncated
        } else {
            hard_lines
        };

        for (i, hard_line) in display_lines.iter().enumerate() {
            let mut spans: Vec<Span> = Vec::new();

            // Left border character for user/assistant messages
            if matches!(msg.role, ChatRole::User | ChatRole::Assistant) {
                spans.push(Span::styled(border_char.to_string(), border_style));
            } else {
                spans.push(Span::styled("  ", Style::default()));
            }

            // Prefix on first line only
            if i == 0 && !prefix.is_empty() {
                spans.push(Span::styled(prefix.to_string(), prefix_style));
            }

            spans.push(Span::styled(hard_line.to_string(), content_style));
            lines.push(Line::from(spans));
        }

        // Collapse hint
        if show_collapse_hint {
            let remaining = total_hard_lines - 3;
            lines.push(Line::from(vec![
                Span::styled("  ", Style::default()),
                Span::styled(
                    format!("  (+{} more lines, ctrl+t to expand)", remaining),
                    theme::dim(theme::SYSTEM_COLOR),
                ),
            ]));
        }

        // Blank line between messages
        lines.push(Line::from(""));
    }

    lines
}

/// Estimate how many terminal rows lines will occupy after soft wrapping.
pub fn line_count_wrapped(lines: &[Line<'_>], width: u16) -> u16 {
    let w = width.saturating_sub(2).max(1) as usize;
    let mut count: u16 = 0;
    for line in lines {
        let char_count: usize = line.spans.iter().map(|s| s.content.len()).sum();
        let wrapped = if char_count == 0 {
            1
        } else {
            ((char_count + w - 1) / w) as u16
        };
        count = count.saturating_add(wrapped);
    }
    count
}

/// The chat message area widget.
pub struct ChatArea<'a> {
    pub messages: &'a [ChatMessage],
    pub scroll_offset: u16,
    pub is_focused: bool,
    pub spinner_text: Option<String>,
}

impl Widget for ChatArea<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let mut lines = render_messages(self.messages, area.width);

        // Append spinner if agent is thinking and no text yet
        if let Some(ref spinner) = self.spinner_text {
            lines.push(Line::from(vec![
                Span::styled("  ", Style::default()),
                Span::styled(spinner.clone(), theme::dim(theme::SYSTEM_COLOR)),
            ]));
        }

        let total_height = line_count_wrapped(&lines, area.width);
        let visible_height = area.height.saturating_sub(2);

        // Auto-scroll to bottom, or use manual offset
        let scroll = if self.scroll_offset > 0 {
            self.scroll_offset
        } else if total_height > visible_height {
            total_height - visible_height
        } else {
            0
        };

        let border_style = if self.is_focused {
            theme::style(theme::BORDER_FOCUSED)
        } else {
            theme::style(theme::BORDER_COLOR)
        };

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Chat ");

        let paragraph = Paragraph::new(lines)
            .block(block)
            .wrap(Wrap { trim: false })
            .scroll((scroll, 0));

        paragraph.render(area, buf);
    }
}
