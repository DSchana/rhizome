//! Status bar — two lines at the bottom showing mode, state, and hints.
//!
//! Line 1: mode indicator + busy state + keybinding hints
//! Line 2: additional context (active topic, etc.)

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::Widget,
};

use crate::tui::tab::SessionMode;
use crate::tui::theme;

/// Data needed to render the status bar.
pub struct StatusInfo {
    pub mode: SessionMode,
    pub is_busy: bool,
    pub active_topic: Option<String>,
    pub tab_count: usize,
}

/// Status bar widget.
pub struct StatusBar<'a> {
    pub info: &'a StatusInfo,
}

impl Widget for StatusBar<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        if area.height == 0 {
            return;
        }

        // Mode indicator
        let (mode_label, mode_color) = match self.info.mode {
            SessionMode::Idle => ("idle", theme::IDLE_COLOR),
            SessionMode::Learn => ("learn", theme::LEARN_COLOR),
            SessionMode::Review => ("review", theme::REVIEW_COLOR),
        };

        let mode_span = Span::styled(
            format!(" ● {} ", mode_label),
            theme::inverted(ratatui::style::Color::Black, mode_color),
        );

        // Busy indicator
        let busy_span = if self.info.is_busy {
            Span::styled(
                " thinking… ",
                theme::inverted(ratatui::style::Color::Black, theme::TOOL_COLOR),
            )
        } else {
            Span::styled("", Style::default())
        };

        // Hints
        let hints = Span::styled(
            " shift+tab: mode │ ctrl+n: new tab │ ctrl+c: cancel/quit │ /: commands ",
            theme::style(theme::DIM_COLOR),
        );

        let line1 = Line::from(vec![mode_span, busy_span, hints]);
        buf.set_line(area.x, area.y, &line1, area.width);

        // Line 2: active topic + tab info (if we have room)
        if area.height >= 2 {
            let mut spans2: Vec<Span> = Vec::new();

            if let Some(ref topic) = self.info.active_topic {
                spans2.push(Span::styled(
                    format!(" topic: {} ", topic),
                    theme::style(theme::ACTIVE_TOPIC_COLOR),
                ));
            }

            if self.info.tab_count > 1 {
                spans2.push(Span::styled(
                    format!(
                        " │ ctrl+pgup/pgdn: switch tabs ({} open) ",
                        self.info.tab_count
                    ),
                    theme::dim(theme::DIM_COLOR),
                ));
            }

            if !spans2.is_empty() {
                let line2 = Line::from(spans2);
                buf.set_line(area.x, area.y + 1, &line2, area.width);
            }
        }
    }
}
