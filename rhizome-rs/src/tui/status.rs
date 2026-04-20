//! Status bar — single line at the bottom showing state and keybindings.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::Widget,
};

/// Current state shown in the status bar.
pub struct StatusInfo {
    pub is_busy: bool,
}

/// A stateless widget that renders the status bar.
pub struct StatusBar<'a> {
    pub info: &'a StatusInfo,
}

impl Widget for StatusBar<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let status_text = if self.info.is_busy {
            Span::styled(
                " ● thinking ",
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            )
        } else {
            Span::styled(
                " ● idle ",
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Green)
                    .add_modifier(Modifier::BOLD),
            )
        };

        let hints = Span::styled(
            " Enter: send │ Ctrl+C: cancel/quit │ Esc: clear ",
            Style::default().fg(Color::DarkGray),
        );

        let line = Line::from(vec![status_text, hints]);
        // Render into the area (single line)
        buf.set_line(area.x, area.y, &line, area.width);
    }
}
