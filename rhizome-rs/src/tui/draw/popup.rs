//! Popup/modal overlay — for interrupt widgets (choices, warnings).
//!
//! Renders a centered bordered box on top of the chat area.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::Style,
    text::{Line, Span},
    widgets::{Block, Borders, Clear, Paragraph, Widget, Wrap},
};

use crate::tui::tab::InterruptKind;
use crate::tui::theme;

/// Interrupt popup widget.
pub struct InterruptPopup<'a> {
    pub interrupt: &'a InterruptKind,
}

impl Widget for InterruptPopup<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        // Size the popup: centered, 60% width, height depends on content
        let popup_width = (area.width * 60 / 100).max(40).min(area.width);
        let popup_x = area.x + (area.width.saturating_sub(popup_width)) / 2;

        match self.interrupt {
            InterruptKind::Choices {
                prompt,
                options,
                cursor,
            } => {
                let height = (options.len() as u16 + 5).min(area.height);
                let popup_y = area.y + (area.height.saturating_sub(height)) / 2;
                let popup_area = Rect {
                    x: popup_x,
                    y: popup_y,
                    width: popup_width,
                    height,
                };

                Clear.render(popup_area, buf);

                let block = Block::default()
                    .borders(Borders::ALL)
                    .border_style(theme::style(theme::BORDER_FOCUSED))
                    .title(" Choose ");
                let inner = block.inner(popup_area);
                block.render(popup_area, buf);

                let mut lines: Vec<Line> = Vec::new();
                lines.push(Line::from(Span::styled(
                    prompt.clone(),
                    theme::bold(theme::ASSISTANT_COLOR),
                )));
                lines.push(Line::from(""));

                for (i, opt) in options.iter().enumerate() {
                    let is_cursor = i == *cursor;
                    let style = if is_cursor {
                        theme::bold(theme::CURSOR_COLOR)
                    } else {
                        theme::style(theme::ASSISTANT_COLOR)
                    };
                    let prefix = if is_cursor { "▸ " } else { "  " };
                    lines.push(Line::from(vec![
                        Span::styled(prefix, theme::style(theme::CURSOR_COLOR)),
                        Span::styled(format!("{}. {}", i + 1, opt), style),
                    ]));
                }

                lines.push(Line::from(""));
                lines.push(Line::from(Span::styled(
                    "  (enter: select, ctrl+c: cancel)",
                    theme::dim(theme::DIM_COLOR),
                )));

                let p = Paragraph::new(lines).wrap(Wrap { trim: false });
                p.render(inner, buf);
            }

            InterruptKind::Warning {
                message,
                options,
                cursor,
            } => {
                let height = (options.len() as u16 + 6).min(area.height);
                let popup_y = area.y + (area.height.saturating_sub(height)) / 2;
                let popup_area = Rect {
                    x: popup_x,
                    y: popup_y,
                    width: popup_width,
                    height,
                };

                Clear.render(popup_area, buf);

                let block = Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(theme::TOOL_COLOR))
                    .title(" ⚠ Warning ");
                let inner = block.inner(popup_area);
                block.render(popup_area, buf);

                let mut lines: Vec<Line> = Vec::new();
                lines.push(Line::from(Span::styled(
                    format!("⚠ {}", message),
                    theme::bold(theme::TOOL_COLOR),
                )));
                lines.push(Line::from(""));

                for (i, opt) in options.iter().enumerate() {
                    let is_cursor = i == *cursor;
                    let style = if is_cursor {
                        theme::bold(theme::CURSOR_COLOR)
                    } else {
                        theme::style(theme::ASSISTANT_COLOR)
                    };
                    let prefix = if is_cursor { "▸ " } else { "  " };
                    lines.push(Line::from(vec![
                        Span::styled(prefix, theme::style(theme::CURSOR_COLOR)),
                        Span::styled(format!("{}. {}", i + 1, opt), style),
                    ]));
                }

                lines.push(Line::from(""));
                lines.push(Line::from(Span::styled(
                    "  (enter: select, ctrl+c: cancel)",
                    theme::dim(theme::DIM_COLOR),
                )));

                let p = Paragraph::new(lines).wrap(Wrap { trim: false });
                p.render(inner, buf);
            }
        }
    }
}
