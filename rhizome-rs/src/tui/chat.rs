//! Chat message area — renders the scrollable message history.
//!
//! Each message is a `ChatMessage` with a role and content string.
//! The widget renders them as a vertical list with role-colored prefixes,
//! automatically wrapping long lines to fit the terminal width.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget, Wrap},
};

/// The role associated with a chat message.
#[derive(Debug, Clone, PartialEq)]
pub enum ChatRole {
    User,
    Assistant,
    /// Inline tool-call status line (e.g. "⚡ list_topics")
    ToolCall,
    /// System-level info (e.g. "Turn complete")
    System,
    Error,
}

/// A single message in the chat history.
#[derive(Debug, Clone)]
pub struct ChatMessage {
    pub role: ChatRole,
    pub content: String,
}

/// Render the full chat history into a set of wrapped `Line`s.
///
/// Returns the lines and the total line count (after wrapping) so the
/// caller can compute scroll offset.
pub fn render_messages(messages: &[ChatMessage], width: u16) -> Vec<Line<'static>> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    let usable_width = width.saturating_sub(2) as usize; // account for block border

    for msg in messages {
        let (prefix, prefix_style) = match msg.role {
            ChatRole::User => (
                "you: ",
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
            ),
            ChatRole::Assistant => ("", Style::default().fg(Color::White)),
            ChatRole::ToolCall => ("", Style::default().fg(Color::Yellow)),
            ChatRole::System => ("", Style::default().fg(Color::DarkGray)),
            ChatRole::Error => (
                "error: ",
                Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
            ),
        };

        let content_style = match msg.role {
            ChatRole::User => Style::default().fg(Color::Cyan),
            ChatRole::Assistant => Style::default().fg(Color::White),
            ChatRole::ToolCall => Style::default().fg(Color::Yellow),
            ChatRole::System => Style::default().fg(Color::DarkGray),
            ChatRole::Error => Style::default().fg(Color::Red),
        };

        // Split content into hard lines (from newlines in the text),
        // then let ratatui's Wrap handle soft wrapping.
        for (i, hard_line) in msg.content.split('\n').enumerate() {
            if i == 0 && !prefix.is_empty() {
                lines.push(Line::from(vec![
                    Span::styled(prefix.to_string(), prefix_style),
                    Span::styled(hard_line.to_string(), content_style),
                ]));
            } else {
                lines.push(Line::from(Span::styled(
                    hard_line.to_string(),
                    content_style,
                )));
            }
        }

        // Blank line between messages
        lines.push(Line::from(""));
    }

    // Estimate total rendered height accounting for soft wraps.
    // This is approximate — ratatui's Paragraph does the real wrapping.
    // We compute it here so the caller can set the scroll offset.
    let _ = usable_width; // used by caller via line_count_wrapped()
    lines
}

/// Estimate how many terminal rows `lines` will occupy after soft wrapping.
pub fn line_count_wrapped(lines: &[Line<'_>], width: u16) -> u16 {
    let w = width.saturating_sub(2).max(1) as usize; // border
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

/// A stateless widget that renders the chat message area.
pub struct ChatArea<'a> {
    pub messages: &'a [ChatMessage],
    pub scroll_offset: u16,
}

impl Widget for ChatArea<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let lines = render_messages(self.messages, area.width);
        let total_height = line_count_wrapped(&lines, area.width);
        let visible_height = area.height.saturating_sub(2); // border

        // Auto-scroll: if content exceeds the area, scroll to the bottom
        let scroll = if total_height > visible_height {
            total_height - visible_height
        } else {
            0
        };
        // Allow manual scroll override (0 = auto-scroll to bottom)
        let scroll = if self.scroll_offset > 0 {
            self.scroll_offset
        } else {
            scroll
        };

        let block = Block::default().borders(Borders::ALL).title(" Chat ");

        let paragraph = Paragraph::new(lines)
            .block(block)
            .wrap(Wrap { trim: false })
            .scroll((scroll, 0));

        paragraph.render(area, buf);
    }
}
