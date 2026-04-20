//! Drawing layer — all ratatui rendering code.
//!
//! The top-level `draw_app` function lays out the tab bar, active tab
//! content, and any overlays (command palette, interrupt popups).

pub mod chat;
pub mod command;
pub mod explorer;
pub mod input;
pub mod popup;
pub mod sidebar;
pub mod spinner;
pub mod status;
pub mod tab_bar;

use ratatui::{
    layout::{Constraint, Layout},
    Frame,
};

use crate::tui::app::App;
use crate::tui::command::COMMANDS;
use crate::tui::focus::FocusTarget;
use chat::ChatArea;
use command::CommandPalette;
use explorer::Explorer;
use popup::InterruptPopup;
use sidebar::Sidebar;
use status::{StatusBar, StatusInfo};
use tab_bar::TabBar;

/// Draw the entire application.
pub fn draw_app(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Vertical layout: tab_bar (1 line) + content + status_bar (2 lines)
    let show_tab_bar = app.tabs.len() > 1;
    let tab_bar_height = if show_tab_bar { 1 } else { 0 };

    let chunks = Layout::vertical([
        Constraint::Length(tab_bar_height),
        Constraint::Min(1),
        Constraint::Length(2),
    ])
    .split(area);

    // Tab bar (only when multiple tabs)
    if show_tab_bar {
        let tab_bar = TabBar {
            tabs: &app.tabs,
            active: app.active_tab,
        };
        frame.render_widget(tab_bar, chunks[0]);
    }

    let tab = app.tab();
    let content_area = chunks[1];

    // Main content area — depends on what's active
    if let Some(ref explorer_state) = tab.explorer {
        // Explorer takes over the full content area
        let explorer = Explorer {
            state: explorer_state,
            is_focused: tab.focus == FocusTarget::Explorer,
        };
        frame.render_widget(explorer, content_area);
    } else {
        // Normal chat layout: optional sidebar + chat + input
        draw_chat_layout(frame, tab, content_area);
    }

    // Status bar
    let status_info = StatusInfo {
        mode: tab.mode,
        is_busy: tab.is_busy,
        active_topic: tab.sidebar.active_topic_id.map(|id| {
            tab.sidebar
                .nodes
                .iter()
                .find(|n| n.id == id)
                .map(|n| n.name.clone())
                .unwrap_or_else(|| format!("Topic #{}", id))
        }),
        tab_count: app.tabs.len(),
    };
    let status = StatusBar { info: &status_info };
    frame.render_widget(status, chunks[2]);

    // Overlays (rendered last, on top of everything)

    // Command palette
    if tab.palette.visible {
        let palette = CommandPalette {
            state: &tab.palette,
            commands: &COMMANDS,
        };
        // Render in the content area (above input)
        frame.render_widget(palette, content_area);
    }

    // Interrupt popup
    if let Some(ref interrupt) = tab.interrupt {
        let popup = InterruptPopup { interrupt };
        frame.render_widget(popup, content_area);
    }
}

/// Draw the normal chat layout (sidebar + chat messages + input).
fn draw_chat_layout(
    frame: &mut Frame,
    tab: &crate::tui::tab::TabState,
    area: ratatui::layout::Rect,
) {
    // Horizontal split: sidebar (if visible) + main column
    let (sidebar_area, main_area) = if tab.sidebar_visible {
        let h_chunks = Layout::horizontal([Constraint::Percentage(25), Constraint::Percentage(75)])
            .split(area);
        (Some(h_chunks[0]), h_chunks[1])
    } else {
        (None, area)
    };

    // Sidebar
    if let Some(sidebar_rect) = sidebar_area {
        let sidebar = Sidebar {
            state: &tab.sidebar,
            is_focused: tab.focus == FocusTarget::Sidebar,
        };
        frame.render_widget(sidebar, sidebar_rect);
    }

    // Vertical split: chat messages + input bar
    let v_chunks = Layout::vertical([Constraint::Min(1), Constraint::Length(3)]).split(main_area);

    // Spinner text
    let spinner_text = if tab.is_busy {
        // Only show spinner if the last message isn't already an assistant message
        // (i.e., we haven't started receiving text yet)
        let last_is_assistant = tab
            .messages
            .last()
            .map(|m| m.role == crate::tui::tab::ChatRole::Assistant)
            .unwrap_or(false);
        if !last_is_assistant {
            Some(spinner::spinner_text(tab.spinner_frame))
        } else {
            None
        }
    } else {
        None
    };

    // Chat area
    let chat = ChatArea {
        messages: &tab.messages,
        scroll_offset: tab.scroll_offset,
        is_focused: tab.focus == FocusTarget::ChatArea,
        spinner_text,
    };
    frame.render_widget(chat, v_chunks[0]);

    // Input bar
    frame.render_widget(&tab.input, v_chunks[1]);
}
