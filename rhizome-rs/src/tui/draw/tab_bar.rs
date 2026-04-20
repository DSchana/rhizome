//! Tab bar widget — horizontal row of tab labels at the top.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::Widget,
};

use crate::tui::tab::{SessionMode, TabState};
use crate::tui::theme;

/// Renders a tab bar from a list of tabs.
pub struct TabBar<'a> {
    pub tabs: &'a [TabState],
    pub active: usize,
}

impl Widget for TabBar<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let mut spans: Vec<Span> = Vec::new();

        for (i, tab) in self.tabs.iter().enumerate() {
            let is_active = i == self.active;

            // Mode indicator dot
            let mode_color = match tab.mode {
                SessionMode::Idle => theme::IDLE_COLOR,
                SessionMode::Learn => theme::LEARN_COLOR,
                SessionMode::Review => theme::REVIEW_COLOR,
            };

            let (label_style, dot_style) = if is_active {
                (
                    theme::inverted(theme::ASSISTANT_COLOR, theme::TAB_ACTIVE_BG),
                    Style::default().fg(mode_color).bg(theme::TAB_ACTIVE_BG),
                )
            } else {
                (
                    theme::style(theme::TAB_INACTIVE_FG),
                    theme::style(mode_color),
                )
            };

            // Separator between tabs
            if i > 0 {
                spans.push(Span::styled(" │ ", theme::style(theme::BORDER_COLOR)));
            }

            spans.push(Span::styled("● ", dot_style));

            // Tab name (truncated to 20 chars)
            let name = if tab.name.len() > 20 {
                format!("{}…", &tab.name[..19])
            } else {
                tab.name.clone()
            };
            spans.push(Span::styled(name, label_style));

            // Busy indicator
            if tab.is_busy {
                spans.push(Span::styled(" ⟳", theme::style(theme::TOOL_COLOR)));
            }
        }

        // Pad remaining space
        let line = Line::from(spans);
        buf.set_line(area.x, area.y, &line, area.width);
    }
}
