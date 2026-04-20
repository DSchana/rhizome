//! Explorer viewer — multi-pane topic + entry browser.
//!
//! Launched via `/explore`. Shows topic tree on the left and entry
//! list with detail panel on the right.

use ratatui::{
    buffer::Buffer,
    layout::{Constraint, Layout, Rect},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget, Wrap},
};

use crate::tui::draw::sidebar::Sidebar;
use crate::tui::tab::{ExplorerState, ExplorerViewMode};
use crate::tui::theme;

/// Explorer viewer widget.
pub struct Explorer<'a> {
    pub state: &'a ExplorerState,
    pub is_focused: bool,
}

impl Widget for Explorer<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let border_style = if self.is_focused {
            theme::style(theme::BORDER_FOCUSED)
        } else {
            theme::style(theme::BORDER_COLOR)
        };

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Explore (tab: view mode, esc: close) ");

        let inner = block.inner(area);
        block.render(area, buf);

        match self.state.view_mode {
            ExplorerViewMode::TopicsOnly => {
                // Full-width topic tree
                let sidebar = Sidebar {
                    state: &self.state.tree,
                    is_focused: self.state.active_pane == 0,
                };
                sidebar.render(inner, buf);
            }
            ExplorerViewMode::TopicsAndEntries => {
                // Split: 30% tree + 70% entries
                let chunks =
                    Layout::horizontal([Constraint::Percentage(30), Constraint::Percentage(70)])
                        .split(inner);

                let sidebar = Sidebar {
                    state: &self.state.tree,
                    is_focused: self.state.active_pane == 0,
                };
                sidebar.render(chunks[0], buf);

                render_entry_list(
                    &self.state.entries,
                    self.state.entry_cursor,
                    self.state.active_pane == 1,
                    chunks[1],
                    buf,
                );
            }
        }
    }
}

/// Render the entry list with a detail panel.
fn render_entry_list(
    entries: &[crate::tui::tab::ExplorerEntry],
    cursor: usize,
    is_focused: bool,
    area: Rect,
    buf: &mut Buffer,
) {
    let border_style = if is_focused {
        theme::style(theme::BORDER_FOCUSED)
    } else {
        theme::style(theme::BORDER_COLOR)
    };

    if entries.is_empty() {
        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Entries ");
        let p = Paragraph::new("  Select a topic to see entries")
            .style(theme::dim(theme::SYSTEM_COLOR))
            .block(block);
        p.render(area, buf);
        return;
    }

    // Split vertically: entry list (top 40%) + detail (bottom 60%)
    let chunks =
        Layout::vertical([Constraint::Percentage(40), Constraint::Percentage(60)]).split(area);

    // Entry list
    let list_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(format!(" Entries ({}) ", entries.len()));

    let list_inner = list_block.inner(chunks[0]);
    list_block.render(chunks[0], buf);

    let mut lines: Vec<Line> = Vec::new();
    for (i, entry) in entries.iter().enumerate() {
        let is_cursor = i == cursor;
        let style = if is_cursor {
            theme::bold(theme::CURSOR_COLOR)
        } else {
            theme::style(theme::ASSISTANT_COLOR)
        };

        let type_str = entry
            .entry_type
            .as_deref()
            .map(|t| format!(" ({})", t))
            .unwrap_or_default();

        let prefix = if is_cursor { "▸ " } else { "  " };

        lines.push(Line::from(vec![
            Span::styled(prefix, theme::style(theme::CURSOR_COLOR)),
            Span::styled(format!("[{}] {}", entry.id, entry.title), style),
            Span::styled(type_str, theme::dim(theme::DIM_COLOR)),
        ]));
    }

    let scroll = if cursor >= list_inner.height as usize {
        cursor - list_inner.height as usize + 1
    } else {
        0
    };

    let list_p = Paragraph::new(lines).scroll((scroll as u16, 0));
    list_p.render(list_inner, buf);

    // Detail panel for selected entry
    let detail_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" Detail ");

    if let Some(entry) = entries.get(cursor) {
        let detail_lines = vec![
            Line::from(Span::styled(
                entry.title.clone(),
                theme::bold(theme::ASSISTANT_COLOR),
            )),
            Line::from(Span::styled(
                format!(
                    "Type: {} │ ID: {}",
                    entry.entry_type.as_deref().unwrap_or("unset"),
                    entry.id
                ),
                theme::dim(theme::DIM_COLOR),
            )),
            Line::from(""),
            Line::from(Span::styled(
                entry.content.clone(),
                theme::style(theme::ASSISTANT_COLOR),
            )),
        ];

        let detail_p = Paragraph::new(detail_lines)
            .block(detail_block)
            .wrap(Wrap { trim: false });
        detail_p.render(chunks[1], buf);
    } else {
        let p = Paragraph::new("").block(detail_block);
        p.render(chunks[1], buf);
    }
}
