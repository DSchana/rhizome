//! Explorer panel — shows the topic tree with entries.

use ratatui::{
    buffer::Buffer,
    layout::{Constraint, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget, Wrap},
};

use super::state::{ExplorerRow, ExplorerState};

const FOCUS_GREEN: Color = Color::Rgb(100, 200, 100);
const DIM: Color = Color::Rgb(100, 100, 100);
const TOPIC_COLOR: Color = Color::Rgb(220, 180, 80);
const ENTRY_COLOR: Color = Color::Rgb(180, 180, 180);
const TYPE_COLOR: Color = Color::Rgb(120, 120, 120);

/// A stateless widget that renders the explorer panel.
pub struct ExplorerWidget<'a> {
    pub state: &'a ExplorerState,
    pub focused: bool,
}

impl Widget for ExplorerWidget<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        if self.state.rows.is_empty() {
            let block = Block::default()
                .borders(Borders::ALL)
                .title(" Explorer ");
            let paragraph = Paragraph::new(Line::from(Span::styled(
                "(No topics — ask the agent to create one)",
                Style::default().fg(DIM).add_modifier(Modifier::ITALIC),
            )))
            .block(block);
            paragraph.render(area, buf);
            return;
        }

        let rows = &self.state.rows;
        let cursor = self.state.cursor;

        // Split: list takes most of the space, detail panel at the bottom
        let chunks = Layout::vertical([
            Constraint::Min(5),
            Constraint::Length(5),
        ])
        .split(area);

        // ── List ─────────────────────────────────────────────────────
        let list_lines: Vec<Line<'_>> = rows
            .iter()
            .enumerate()
            .map(|(i, row)| {
                let is_selected = cursor == i;
                render_explorer_row(row, is_selected, self.focused)
            })
            .collect();

        let list_block = Block::default()
            .borders(Borders::ALL)
            .title(" Explorer ");
        let visible = chunks[0].height.saturating_sub(2); // borders
        let scroll = if (cursor as u16) >= visible {
            (cursor as u16).saturating_sub(visible - 1)
        } else {
            0
        };
        let list_paragraph = Paragraph::new(list_lines)
            .block(list_block)
            .scroll((scroll, 0));
        list_paragraph.render(chunks[0], buf);

        // ── Detail Panel ─────────────────────────────────────────────
        let detail_lines = render_detail(&rows[std::cmp::min(cursor, rows.len() - 1)]);
        let detail_block = Block::default()
            .borders(Borders::ALL)
            .title(" Details ");
        let detail_paragraph = Paragraph::new(detail_lines)
            .block(detail_block)
            .wrap(Wrap { trim: false });
        detail_paragraph.render(chunks[1], buf);
    }
}

fn render_explorer_row<'a>(row: &ExplorerRow, is_selected: bool, focused: bool) -> Line<'a> {
    let marker = if is_selected { "► " } else { "  " };

    match row {
        ExplorerRow::Topic { name, depth, entry_count, .. } => {
            let indent = "  ".repeat(*depth);
            let icon = "▸ ";

            let base_style = if is_selected && focused {
                Style::default().fg(FOCUS_GREEN).add_modifier(Modifier::BOLD)
            } else if is_selected {
                Style::default().fg(TOPIC_COLOR).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(TOPIC_COLOR)
            };

            let count_text = format!("  ({} entries)", entry_count);

            Line::from(vec![
                Span::styled(marker.to_string(), base_style),
                Span::raw(indent),
                Span::styled(icon.to_string(), base_style),
                Span::styled(name.clone(), base_style),
                Span::styled(count_text, Style::default().fg(DIM)),
            ])
        }

        ExplorerRow::Entry { title, entry_type, depth, .. } => {
            let indent = "  ".repeat(*depth);
            let icon = "  ";

            let base_style = if is_selected && focused {
                Style::default().fg(FOCUS_GREEN).add_modifier(Modifier::BOLD)
            } else if is_selected {
                Style::default().fg(ENTRY_COLOR).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(ENTRY_COLOR)
            };

            let mut spans = vec![
                Span::styled(marker.to_string(), base_style),
                Span::raw(indent),
                Span::raw(icon.to_string()),
                Span::styled(title.clone(), base_style),
            ];

            if let Some(etype) = entry_type {
                spans.push(Span::styled(
                    format!("  [{}]", etype),
                    Style::default().fg(TYPE_COLOR),
                ));
            }

            Line::from(spans)
        }
    }
}

fn render_detail<'a>(row: &ExplorerRow) -> Vec<Line<'a>> {
    match row {
        ExplorerRow::Topic { id, name, entry_count, .. } => {
            vec![
                Line::from(Span::styled(
                    name.clone(),
                    Style::default().add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!("Topic ID: {}  |  {} entries", id, entry_count),
                    Style::default().fg(DIM),
                )),
            ]
        }

        ExplorerRow::Entry { id, title, entry_type, .. } => {
            let type_str = entry_type.as_deref().unwrap_or("entry");
            vec![
                Line::from(Span::styled(
                    title.clone(),
                    Style::default().add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!("Entry ID: {}  |  Type: {}", id, type_str),
                    Style::default().fg(DIM),
                )),
            ]
        }
    }
}
