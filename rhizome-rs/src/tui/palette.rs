//! Command palette — filtered dropdown for slash commands.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Widget},
};

use super::commands;
use super::state::CommandPaletteState;

const HIGHLIGHT_BG: Color = Color::Rgb(86, 126, 160);
const DIM_TEXT: Color = Color::Rgb(150, 150, 150);

/// A stateless widget that renders the command palette dropdown.
pub struct CommandPalette<'a> {
    pub state: &'a CommandPaletteState,
}

impl Widget for CommandPalette<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let filtered = commands::filter_commands(&self.state.filter);
        if filtered.is_empty() {
            return;
        }

        let max_name_len = filtered.iter().map(|c| c.name.len()).max().unwrap_or(0);

        let lines: Vec<Line<'_>> = filtered
            .iter()
            .enumerate()
            .map(|(i, cmd)| {
                let is_selected = i == self.state.selected_index;
                let padded_name = format!("/{:<width$}", cmd.name, width = max_name_len);
                let text = format!("{}  — {}", padded_name, cmd.description);

                let style = if is_selected {
                    Style::default().fg(Color::White).bg(HIGHLIGHT_BG)
                } else {
                    Style::default().fg(DIM_TEXT)
                };

                Line::from(Span::styled(text, style))
            })
            .collect();

        let block = Block::default().borders(Borders::ALL).title(" Commands ");
        let paragraph = Paragraph::new(lines).block(block);
        paragraph.render(area, buf);
    }
}
