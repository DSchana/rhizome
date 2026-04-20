//! TUI application — main loop, event dispatch, and terminal lifecycle.

pub mod app;
pub mod command;
pub mod draw;
pub mod event;
pub mod focus;
pub mod input_history;
pub mod tab;
pub mod theme;

// Re-export input helpers (used by tab.rs)
pub mod input {
    pub use super::draw::input::*;
}

use crossterm::{
    event::{KeyCode, KeyEvent, KeyModifiers},
    terminal::{self, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use tokio::sync::mpsc;

use crate::agent::AgentEvent;
use app::App;
use command::CommandAction;
use draw::draw_app;
use event::{spawn_event_reader, AppEvent};
use focus::FocusTarget;
use tab::{ChatMessage, ChatRole, ExplorerEntry, ExplorerState, InterruptKind};

/// Run the TUI application. Takes ownership of resources.
pub async fn run(
    api_key: String,
    pool: sqlx::SqlitePool,
) -> anyhow::Result<()> {
    std::io::stdout().execute(EnterAlternateScreen)?;
    terminal::enable_raw_mode()?;

    let terminal = ratatui::init();
    let result = run_app(terminal, api_key, pool).await;

    ratatui::restore();
    terminal::disable_raw_mode().ok();
    std::io::stdout().execute(LeaveAlternateScreen).ok();

    result
}

async fn run_app(
    mut terminal: ratatui::DefaultTerminal,
    api_key: String,
    pool: sqlx::SqlitePool,
) -> anyhow::Result<()> {
    let (app_tx, mut app_rx) = mpsc::channel::<AppEvent>(256);

    spawn_event_reader(app_tx.clone());

    let mut app = App::new(api_key, pool, app_tx.clone());
    app.new_tab();

    // Load initial sidebar data for the first tab
    {
        let pool = app.pool().clone();
        let tab = app.tab_mut();
        load_sidebar_roots(&mut tab.sidebar, &pool).await;
    }

    while !app.should_quit {
        // Refresh sidebar data if needed
        {
            let pool = app.pool().clone();
            let tab = app.tab_mut();
            if tab.sidebar.needs_refresh {
                load_sidebar_roots(&mut tab.sidebar, &pool).await;
            }
            if let Some(ref mut explorer) = tab.explorer {
                if explorer.tree.needs_refresh {
                    load_sidebar_roots(&mut explorer.tree, &pool).await;
                }
            }
        }

        terminal.draw(|frame| draw_app(frame, &app))?;

        let Some(event) = app_rx.recv().await else {
            break;
        };

        match event {
            AppEvent::Key(key) => handle_key(key, &mut app).await,
            AppEvent::Agent(tab_idx, agent_event) => {
                handle_agent_event(tab_idx, agent_event, &mut app);
            }
            AppEvent::Resize(_, _) => {}
            AppEvent::Tick => {
                for tab in &mut app.tabs {
                    if tab.is_busy {
                        tab.spinner_frame = draw::spinner::advance_frame(tab.spinner_frame);
                    }
                }
            }
        }
    }

    Ok(())
}

// ── Key handling ─────────────────────────────────────────────────────

async fn handle_key(key: KeyEvent, app: &mut App) {
    // Global bindings (always active)
    match (key.code, key.modifiers) {
        (KeyCode::Char('n'), KeyModifiers::CONTROL) => {
            app.new_tab();
            let pool = app.pool().clone();
            load_sidebar_roots(&mut app.tab_mut().sidebar, &pool).await;
            return;
        }
        (KeyCode::Char('w'), KeyModifiers::CONTROL) => {
            app.close_active_tab();
            return;
        }
        (KeyCode::PageDown, KeyModifiers::CONTROL) => {
            app.next_tab();
            return;
        }
        (KeyCode::PageUp, KeyModifiers::CONTROL) => {
            app.prev_tab();
            return;
        }
        (KeyCode::BackTab, _) => {
            let tab = app.tab_mut();
            tab.mode = tab.mode.next();
            return;
        }
        _ => {}
    }

    // Route to the focused element
    let focus = app.tab().focus;
    match focus {
        FocusTarget::Input => handle_input_key(key, app),
        FocusTarget::ChatArea => handle_chat_key(key, app.tab_mut()),
        FocusTarget::Sidebar => {
            let pool = app.pool().clone();
            handle_sidebar_key(key, app.tab_mut(), &pool).await;
        }
        FocusTarget::Explorer => {
            let pool = app.pool().clone();
            handle_explorer_key(key, app.tab_mut(), &pool).await;
        }
        FocusTarget::CommandPalette => handle_palette_key(key, app),
        FocusTarget::Interrupt => handle_interrupt_key(key, app.tab_mut()),
    }
}

fn handle_input_key(key: KeyEvent, app: &mut App) {
    let tab = app.tab_mut();

    match (key.code, key.modifiers) {
        // Ctrl+C
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            if tab.is_busy {
                tab.messages.push(ChatMessage::new(ChatRole::System, "Cancelled.".into()));
                tab.is_busy = false;
                draw::input::set_busy(&mut tab.input, false);
            } else if tab.input.lines().join("").trim().is_empty() {
                app.should_quit = true;
            } else {
                tab.input.select_all();
                tab.input.cut();
            }
        }

        // Escape
        (KeyCode::Esc, _) => {
            if tab.palette.visible {
                tab.palette.visible = false;
            } else {
                tab.input.select_all();
                tab.input.cut();
            }
        }

        // Ctrl+E: toggle sidebar
        (KeyCode::Char('e'), KeyModifiers::CONTROL) => {
            tab.sidebar_visible = !tab.sidebar_visible;
            if tab.sidebar_visible {
                tab.sidebar.needs_refresh = true;
            }
        }

        // Ctrl+T: toggle collapse on last assistant message
        (KeyCode::Char('t'), KeyModifiers::CONTROL) => {
            if let Some(msg) = tab.messages.iter_mut().rev().find(|m| m.role == ChatRole::Assistant) {
                msg.collapsed = !msg.collapsed;
            }
        }

        // Focus switching
        (KeyCode::Left, KeyModifiers::CONTROL) => {
            if tab.sidebar_visible {
                tab.focus = FocusTarget::Sidebar;
            }
        }
        (KeyCode::Right, KeyModifiers::CONTROL) => {
            tab.focus = FocusTarget::ChatArea;
        }

        // Up at top: history
        (KeyCode::Up, KeyModifiers::NONE) => {
            let cursor = tab.input.cursor();
            if cursor == (0, 0) {
                let current = tab.input.lines().join("\n");
                if let Some(prev) = tab.history.prev(&current) {
                    let prev = prev.to_string();
                    draw::input::set_text(&mut tab.input, &prev);
                }
            } else {
                tab.input.input(key);
            }
        }
        (KeyCode::Down, KeyModifiers::NONE) => {
            let cursor = tab.input.cursor();
            let line_count = tab.input.lines().len();
            if cursor.0 == line_count - 1 {
                if let Some(next) = tab.history.next() {
                    let next = next.to_string();
                    draw::input::set_text(&mut tab.input, &next);
                }
            } else {
                tab.input.input(key);
            }
        }

        // Enter: submit
        (KeyCode::Enter, KeyModifiers::NONE) => {
            if tab.is_busy {
                return;
            }

            // Palette confirm
            if tab.palette.visible {
                let filter = tab.palette.filter.clone();
                let filtered: Vec<&command::CommandDef> = command::COMMANDS
                    .iter()
                    .filter(|c| filter.is_empty() || c.name.contains(&filter))
                    .collect();
                if let Some(cmd) = filtered.get(tab.palette.selected) {
                    draw::input::set_text(&mut tab.input, &format!("/{}", cmd.name));
                }
                tab.palette.visible = false;
                tab.palette.selected = 0;
                return;
            }

            if let Some(user_text) = draw::input::take_input(&mut tab.input) {
                tab.history.push(user_text.clone());
                tab.history.reset_position();

                // Slash command
                if user_text.starts_with('/') {
                    let action = command::execute(&user_text);
                    execute_command_action(action, app);
                    return;
                }

                // Chat message
                tab.messages.push(ChatMessage::new(ChatRole::User, user_text.clone()));
                tab.scroll_offset = 0;
                tab.is_busy = true;
                tab.tool_calls.clear();
                draw::input::set_busy(&mut tab.input, true);

                if tab.cmd_tx.try_send(user_text).is_err() {
                    tab.messages.push(ChatMessage::new(ChatRole::Error, "Agent is not available.".into()));
                    tab.is_busy = false;
                    draw::input::set_busy(&mut tab.input, false);
                }
            }
        }

        // Other keys: forward to textarea + palette logic
        _ => {
            tab.input.input(key);
            let text = tab.input.lines().join("");
            if text.starts_with('/') && !text.contains(' ') {
                tab.palette.visible = true;
                tab.palette.filter = text[1..].to_string();
                tab.palette.selected = 0;
            } else {
                tab.palette.visible = false;
            }
            draw::input::set_shell_mode(&mut tab.input, text.starts_with('!'));
        }
    }
}

fn handle_chat_key(key: KeyEvent, tab: &mut tab::TabState) {
    match (key.code, key.modifiers) {
        (KeyCode::Up, KeyModifiers::NONE) | (KeyCode::PageUp, KeyModifiers::NONE) => {
            tab.scroll_offset = tab.scroll_offset.saturating_add(3);
        }
        (KeyCode::Down, KeyModifiers::NONE) | (KeyCode::PageDown, KeyModifiers::NONE) => {
            tab.scroll_offset = tab.scroll_offset.saturating_sub(3);
        }
        (KeyCode::Home, _) => tab.scroll_offset = u16::MAX,
        (KeyCode::End, _) => tab.scroll_offset = 0,
        (KeyCode::Esc, _) | (KeyCode::Char('l'), KeyModifiers::CONTROL) => {
            tab.focus = FocusTarget::Input;
        }
        (KeyCode::Char('t'), KeyModifiers::CONTROL) => {
            if let Some(msg) = tab.messages.iter_mut().rev().find(|m| m.role == ChatRole::Assistant) {
                msg.collapsed = !msg.collapsed;
            }
        }
        _ => {}
    }
}

async fn handle_sidebar_key(key: KeyEvent, tab: &mut tab::TabState, pool: &sqlx::SqlitePool) {
    match (key.code, key.modifiers) {
        (KeyCode::Up, KeyModifiers::NONE) => {
            if tab.sidebar.cursor > 0 { tab.sidebar.cursor -= 1; }
        }
        (KeyCode::Down, KeyModifiers::NONE) => {
            if tab.sidebar.cursor + 1 < tab.sidebar.nodes.len() { tab.sidebar.cursor += 1; }
        }
        (KeyCode::Right, KeyModifiers::NONE) => {
            if let Some(node) = tab.sidebar.nodes.get(tab.sidebar.cursor) {
                if node.has_children && !node.expanded {
                    let id = node.id;
                    expand_tree_node(&mut tab.sidebar, id, pool).await;
                } else if node.expanded && tab.sidebar.cursor + 1 < tab.sidebar.nodes.len() {
                    let d = node.depth;
                    if tab.sidebar.nodes[tab.sidebar.cursor + 1].depth == d + 1 {
                        tab.sidebar.cursor += 1;
                    }
                }
            }
        }
        (KeyCode::Left, KeyModifiers::NONE) => {
            if let Some(node) = tab.sidebar.nodes.get(tab.sidebar.cursor) {
                if node.expanded {
                    let id = node.id;
                    collapse_tree_node(&mut tab.sidebar, id);
                } else if node.depth > 0 {
                    let d = node.depth;
                    for i in (0..tab.sidebar.cursor).rev() {
                        if tab.sidebar.nodes[i].depth < d {
                            tab.sidebar.cursor = i;
                            break;
                        }
                    }
                }
            }
        }
        (KeyCode::Char('j'), KeyModifiers::CONTROL) => {
            if let Some(node) = tab.sidebar.nodes.get(tab.sidebar.cursor) {
                tab.sidebar.active_topic_id = Some(node.id);
            }
        }
        (KeyCode::Esc, _) | (KeyCode::Char('l'), KeyModifiers::CONTROL) => {
            tab.focus = FocusTarget::Input;
        }
        (KeyCode::Right, KeyModifiers::CONTROL) => {
            tab.focus = FocusTarget::Input;
        }
        _ => {}
    }
}

async fn handle_explorer_key(key: KeyEvent, tab: &mut tab::TabState, pool: &sqlx::SqlitePool) {
    let explorer = match tab.explorer.as_mut() {
        Some(e) => e,
        None => return,
    };

    match (key.code, key.modifiers) {
        (KeyCode::Tab, KeyModifiers::NONE) => {
            explorer.view_mode = explorer.view_mode.next();
        }
        (KeyCode::Left, KeyModifiers::CONTROL) => {
            if explorer.active_pane > 0 { explorer.active_pane -= 1; }
        }
        (KeyCode::Right, KeyModifiers::CONTROL) => {
            let max = match explorer.view_mode {
                tab::ExplorerViewMode::TopicsOnly => 1,
                tab::ExplorerViewMode::TopicsAndEntries => 2,
            };
            if explorer.active_pane + 1 < max { explorer.active_pane += 1; }
        }
        (KeyCode::Up, KeyModifiers::NONE) => {
            if explorer.active_pane == 0 {
                if explorer.tree.cursor > 0 { explorer.tree.cursor -= 1; }
            } else if explorer.entry_cursor > 0 {
                explorer.entry_cursor -= 1;
            }
        }
        (KeyCode::Down, KeyModifiers::NONE) => {
            if explorer.active_pane == 0 {
                if explorer.tree.cursor + 1 < explorer.tree.nodes.len() { explorer.tree.cursor += 1; }
            } else if explorer.entry_cursor + 1 < explorer.entries.len() {
                explorer.entry_cursor += 1;
            }
        }
        (KeyCode::Right, KeyModifiers::NONE) if explorer.active_pane == 0 => {
            if let Some(node) = explorer.tree.nodes.get(explorer.tree.cursor) {
                if node.has_children && !node.expanded {
                    let id = node.id;
                    expand_tree_node(&mut explorer.tree, id, pool).await;
                }
            }
        }
        (KeyCode::Left, KeyModifiers::NONE) if explorer.active_pane == 0 => {
            if let Some(node) = explorer.tree.nodes.get(explorer.tree.cursor) {
                if node.expanded {
                    let id = node.id;
                    collapse_tree_node(&mut explorer.tree, id);
                } else if node.depth > 0 {
                    let d = node.depth;
                    for i in (0..explorer.tree.cursor).rev() {
                        if explorer.tree.nodes[i].depth < d {
                            explorer.tree.cursor = i;
                            break;
                        }
                    }
                }
            }
        }
        (KeyCode::Char('j'), KeyModifiers::CONTROL) => {
            if let Some(node) = explorer.tree.nodes.get(explorer.tree.cursor) {
                let id = node.id;
                explorer.tree.active_topic_id = Some(id);
                load_explorer_entries(explorer, id, pool).await;
            }
        }
        (KeyCode::Esc, _) => {
            tab.explorer = None;
            tab.focus = FocusTarget::Input;
        }
        _ => {}
    }
}

fn handle_palette_key(key: KeyEvent, app: &mut App) {
    let tab = app.tab_mut();
    let filter = tab.palette.filter.clone();
    let filtered_count = command::COMMANDS
        .iter()
        .filter(|c| filter.is_empty() || c.name.contains(&filter))
        .count();

    match key.code {
        KeyCode::Up => {
            if tab.palette.selected > 0 { tab.palette.selected -= 1; }
        }
        KeyCode::Down => {
            if tab.palette.selected + 1 < filtered_count { tab.palette.selected += 1; }
        }
        KeyCode::Enter | KeyCode::Tab => {
            let filtered: Vec<&command::CommandDef> = command::COMMANDS
                .iter()
                .filter(|c| filter.is_empty() || c.name.contains(&filter))
                .collect();
            if let Some(cmd) = filtered.get(tab.palette.selected) {
                draw::input::set_text(&mut tab.input, &format!("/{}", cmd.name));
            }
            tab.palette.visible = false;
            tab.focus = FocusTarget::Input;
        }
        KeyCode::Esc => {
            tab.palette.visible = false;
            tab.focus = FocusTarget::Input;
        }
        _ => {
            tab.input.input(key);
            let text = tab.input.lines().join("");
            if text.starts_with('/') && !text.contains(' ') {
                tab.palette.filter = text[1..].to_string();
                tab.palette.selected = 0;
            } else {
                tab.palette.visible = false;
                tab.focus = FocusTarget::Input;
            }
        }
    }
}

fn handle_interrupt_key(key: KeyEvent, tab: &mut tab::TabState) {
    let interrupt = match tab.interrupt.as_mut() {
        Some(i) => i,
        None => { tab.focus = FocusTarget::Input; return; }
    };

    match interrupt {
        InterruptKind::Choices { options, cursor, .. }
        | InterruptKind::Warning { options, cursor, .. } => {
            match key.code {
                KeyCode::Up => { if *cursor > 0 { *cursor -= 1; } }
                KeyCode::Down => { if *cursor + 1 < options.len() { *cursor += 1; } }
                KeyCode::Enter => {
                    let selected = options.get(*cursor).cloned().unwrap_or_default();
                    tab.messages.push(ChatMessage::new(ChatRole::System, format!("Selected: {}", selected)));
                    tab.interrupt = None;
                    tab.focus = FocusTarget::Input;
                }
                KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    tab.messages.push(ChatMessage::new(ChatRole::System, "Cancelled.".into()));
                    tab.interrupt = None;
                    tab.focus = FocusTarget::Input;
                }
                _ => {}
            }
        }
    }
}

// ── Command execution ────────────────────────────────────────────────

fn execute_command_action(action: CommandAction, app: &mut App) {
    match action {
        CommandAction::None => {}
        CommandAction::Message(msg) => {
            app.tab_mut().messages.push(ChatMessage::new(ChatRole::System, msg));
        }
        CommandAction::Clear => { app.tab_mut().messages.clear(); }
        CommandAction::Quit => { app.should_quit = true; }
        CommandAction::NewTab => { app.new_tab(); }
        CommandAction::CloseTab => { app.close_active_tab(); }
        CommandAction::SetMode(mode) => { app.tab_mut().mode = mode; }
        CommandAction::ToggleSidebar => {
            let tab = app.tab_mut();
            tab.sidebar_visible = !tab.sidebar_visible;
            if tab.sidebar_visible { tab.sidebar.needs_refresh = true; }
        }
        CommandAction::ToggleExplorer => {
            let tab = app.tab_mut();
            if tab.explorer.is_some() {
                tab.explorer = None;
                tab.focus = FocusTarget::Input;
            } else {
                let mut explorer = ExplorerState::new();
                explorer.tree.needs_refresh = true;
                tab.explorer = Some(explorer);
                tab.focus = FocusTarget::Explorer;
            }
        }
        CommandAction::Rename(name) => { app.tab_mut().name = name; }
    }
}

// ── Agent event handling ─────────────────────────────────────────────

fn handle_agent_event(tab_idx: usize, event: AgentEvent, app: &mut App) {
    let tab = match app.tabs.get_mut(tab_idx) {
        Some(t) => t,
        None => return,
    };

    match event {
        AgentEvent::TextDelta(text) => {
            if let Some(last) = tab.messages.last_mut() {
                if last.role == ChatRole::Assistant {
                    last.content.push_str(&text);
                    tab.scroll_offset = 0;
                    return;
                }
            }
            tab.messages.push(ChatMessage::new(ChatRole::Assistant, text));
            tab.scroll_offset = 0;
        }
        AgentEvent::ToolCallStart { name } => {
            tab.tool_calls.push(tab::ToolCallState {
                name: name.clone(),
                result: None,
                collapsed: false,
            });
            tab.messages.push(ChatMessage::new(ChatRole::ToolCall, format!("⚡ {}", name)));
        }
        AgentEvent::ToolCallResult { name, result } => {
            if let Some(tc) = tab.tool_calls.iter_mut().find(|tc| tc.name == name && tc.result.is_none()) {
                tc.result = Some(result.clone());
            }
            if let Some(last) = tab.messages.last_mut() {
                if last.role == ChatRole::ToolCall && last.content.contains(&name) {
                    let display = if result.len() > 200 { format!("{}…", &result[..200]) } else { result };
                    last.content = format!("✓ {} — {}", name, display);
                    return;
                }
            }
            tab.messages.push(ChatMessage::new(ChatRole::ToolCall, format!("✓ {} — done", name)));
        }
        AgentEvent::TurnComplete => {
            tab.is_busy = false;
            tab.tool_calls.clear();
            draw::input::set_busy(&mut tab.input, false);
        }
        AgentEvent::Error(msg) => {
            tab.messages.push(ChatMessage::new(ChatRole::Error, msg));
            tab.is_busy = false;
            tab.tool_calls.clear();
            draw::input::set_busy(&mut tab.input, false);
        }
    }
}

// ── Tree operations ──────────────────────────────────────────────────

async fn load_sidebar_roots(state: &mut tab::SidebarState, pool: &sqlx::SqlitePool) {
    use crate::db::topics;

    state.nodes.clear();
    if let Ok(roots) = topics::list_root_topics(pool).await {
        let counts: Vec<(i64, i64)> = sqlx::query_as(
            "SELECT topic_id, COUNT(*) FROM knowledge_entry GROUP BY topic_id",
        )
        .fetch_all(pool)
        .await
        .unwrap_or_default();
        let count_map: std::collections::HashMap<i64, i64> = counts.into_iter().collect();

        let children_check: Vec<(i64,)> = sqlx::query_as(
            "SELECT DISTINCT parent_id FROM topic WHERE parent_id IS NOT NULL",
        )
        .fetch_all(pool)
        .await
        .unwrap_or_default();
        let parents: std::collections::HashSet<i64> = children_check.into_iter().map(|(id,)| id).collect();

        for root in roots {
            state.nodes.push(tab::TreeNode {
                entry_count: count_map.get(&root.id).copied().unwrap_or(0),
                has_children: parents.contains(&root.id),
                id: root.id,
                name: root.name,
                depth: 0,
                expanded: false,
            });
        }
    }
    state.needs_refresh = false;
}

async fn expand_tree_node(state: &mut tab::SidebarState, topic_id: i64, pool: &sqlx::SqlitePool) {
    use crate::db::topics;

    let (idx, depth) = match state.nodes.iter().position(|n| n.id == topic_id) {
        Some(i) => { state.nodes[i].expanded = true; (i, state.nodes[i].depth) }
        None => return,
    };

    if let Ok(children) = topics::list_children(pool, topic_id).await {
        let counts: Vec<(i64, i64)> = sqlx::query_as(
            "SELECT topic_id, COUNT(*) FROM knowledge_entry GROUP BY topic_id",
        )
        .fetch_all(pool).await.unwrap_or_default();
        let count_map: std::collections::HashMap<i64, i64> = counts.into_iter().collect();

        let children_check: Vec<(i64,)> = sqlx::query_as(
            "SELECT DISTINCT parent_id FROM topic WHERE parent_id IS NOT NULL",
        )
        .fetch_all(pool).await.unwrap_or_default();
        let parents: std::collections::HashSet<i64> = children_check.into_iter().map(|(id,)| id).collect();

        let mut insert_pos = idx + 1;
        for child in children {
            state.nodes.insert(insert_pos, tab::TreeNode {
                entry_count: count_map.get(&child.id).copied().unwrap_or(0),
                has_children: parents.contains(&child.id),
                id: child.id,
                name: child.name,
                depth: depth + 1,
                expanded: false,
            });
            insert_pos += 1;
        }
    }
}

fn collapse_tree_node(state: &mut tab::SidebarState, topic_id: i64) {
    let idx = match state.nodes.iter().position(|n| n.id == topic_id) {
        Some(i) => i,
        None => return,
    };

    let depth = state.nodes[idx].depth;
    state.nodes[idx].expanded = false;

    let mut remove_count = 0;
    for node in &state.nodes[idx + 1..] {
        if node.depth > depth { remove_count += 1; } else { break; }
    }
    state.nodes.drain(idx + 1..idx + 1 + remove_count);

    if state.cursor > idx && state.cursor <= idx + remove_count {
        state.cursor = idx;
    } else if state.cursor > idx + remove_count {
        state.cursor -= remove_count;
    }
}

async fn load_explorer_entries(explorer: &mut ExplorerState, topic_id: i64, pool: &sqlx::SqlitePool) {
    use crate::db::entries;

    explorer.entries.clear();
    explorer.entry_cursor = 0;

    if let Ok(db_entries) = entries::list_entries(pool, topic_id).await {
        for e in db_entries {
            explorer.entries.push(ExplorerEntry {
                id: e.id,
                title: e.title,
                entry_type: e.entry_type.map(|t| format!("{:?}", t).to_lowercase()),
                content: e.content,
            });
        }
    }
}
