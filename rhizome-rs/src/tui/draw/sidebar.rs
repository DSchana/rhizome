//! Topic tree sidebar — interactive tree widget for browsing topics.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget},
};

use crate::tui::tab::SidebarState;
use crate::tui::theme;

/// Sidebar widget.
pub struct Sidebar<'a> {
    pub state: &'a SidebarState,
    pub is_focused: bool,
}

impl Widget for Sidebar<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let border_style = if self.is_focused {
            theme::style(theme::BORDER_FOCUSED)
        } else {
            theme::style(theme::BORDER_COLOR)
        };

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Topics (ctrl+e) ");

        let inner = block.inner(area);
        block.render(area, buf);

        if self.state.nodes.is_empty() {
            let hint = Paragraph::new("  Loading...").style(theme::dim(theme::SYSTEM_COLOR));
            hint.render(inner, buf);
            return;
        }

        let mut lines: Vec<Line> = Vec::new();
        for (i, node) in self.state.nodes.iter().enumerate() {
            let is_cursor = i == self.state.cursor;
            let is_active = Some(node.id) == self.state.active_topic_id;

            let indent = "  ".repeat(node.depth);
            let icon = if node.has_children {
                if node.expanded {
                    "▼ "
                } else {
                    "▶ "
                }
            } else {
                "  "
            };

            let name_style = if is_cursor {
                theme::bold(theme::CURSOR_COLOR)
            } else if is_active {
                theme::bold(theme::ACTIVE_TOPIC_COLOR)
            } else {
                theme::style(theme::ASSISTANT_COLOR)
            };

            let count_str = format!(" ({})", node.entry_count);

            let mut spans = vec![
                Span::styled(indent, Style::default()),
                Span::styled(icon.to_string(), theme::dim(theme::DIM_COLOR)),
                Span::styled(node.name.clone(), name_style),
                Span::styled(count_str, theme::dim(theme::DIM_COLOR)),
            ];

            if is_cursor {
                // Cursor indicator
                spans.insert(0, Span::styled("▸", theme::style(theme::CURSOR_COLOR)));
            } else {
                spans.insert(0, Span::styled(" ", Style::default()));
            }

            lines.push(Line::from(spans));
        }

        // Scroll if needed
        let visible = inner.height as usize;
        let scroll = if self.state.cursor >= visible {
            self.state.cursor - visible + 1
        } else {
            0
        };

        let paragraph = Paragraph::new(lines).scroll((scroll as u16, 0));
        paragraph.render(inner, buf);
    }
}
