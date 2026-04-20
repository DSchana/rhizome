//! Command palette popup — filtered dropdown of slash commands.
//!
//! Rendered as an overlay on top of the chat area when the input
//! starts with `/`.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::{Block, Borders, Clear, Paragraph, Widget},
};

use crate::tui::command::CommandDef;
use crate::tui::tab::PaletteState;
use crate::tui::theme;

/// Command palette overlay widget.
pub struct CommandPalette<'a> {
    pub state: &'a PaletteState,
    pub commands: &'a [CommandDef],
}

impl Widget for CommandPalette<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        if !self.state.visible {
            return;
        }

        // Filter commands by the current input
        let filter = self.state.filter.to_lowercase();
        let filtered: Vec<&CommandDef> = self
            .commands
            .iter()
            .filter(|c| {
                filter.is_empty()
                    || c.name.contains(&filter)
                    || c.description.to_lowercase().contains(&filter)
            })
            .collect();

        if filtered.is_empty() {
            return;
        }

        // Position: above the input bar, full width, up to 10 rows
        let height = (filtered.len() as u16 + 2).min(12).min(area.height);
        let popup_area = Rect {
            x: area.x,
            y: area.y.saturating_add(area.height).saturating_sub(height),
            width: area.width,
            height,
        };

        // Clear the background
        Clear.render(popup_area, buf);

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(theme::style(theme::BORDER_COLOR))
            .style(Style::default().bg(theme::PALETTE_BG))
            .title(" Commands ");

        let inner = block.inner(popup_area);
        block.render(popup_area, buf);

        let mut lines: Vec<Line> = Vec::new();
        for (i, cmd) in filtered.iter().enumerate() {
            let is_selected = i == self.state.selected;
            let (name_style, desc_style) = if is_selected {
                (
                    theme::inverted(theme::ASSISTANT_COLOR, theme::PALETTE_SELECTED_BG),
                    theme::inverted(theme::DIM_COLOR, theme::PALETTE_SELECTED_BG),
                )
            } else {
                (
                    theme::bold(theme::ASSISTANT_COLOR),
                    theme::style(theme::DIM_COLOR),
                )
            };

            lines.push(Line::from(vec![
                Span::styled(format!(" /{}", cmd.name), name_style),
                Span::styled(format!("  — {}", cmd.description), desc_style),
            ]));
        }

        let p = Paragraph::new(lines);
        p.render(inner, buf);
    }
}
