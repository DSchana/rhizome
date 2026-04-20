//! TUI application — ratatui main loop, layout, and state management.
//!
//! Architecture:
//! - The agent owns its own tokio task, receiving user text via a command channel.
//! - The agent sends AgentEvents to the TUI via a second channel.
//! - A third channel merges terminal events (keys, resize) with agent events
//!   and ticks into a single AppEvent stream for the main loop.

pub mod chat;
pub mod commands;
pub mod event;
pub mod explorer;
pub mod input;
pub mod palette;
pub mod state;
pub mod status;

use crossterm::{
    event::{KeyCode, KeyEvent, KeyModifiers},
    terminal::{self, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use ratatui::{
    layout::{Constraint, Layout},
    DefaultTerminal, Frame,
};
use sqlx::SqlitePool;
use tokio::sync::mpsc;

use crate::agent::{Agent, AgentEvent};
use chat::{ChatArea, ChatMessage, ChatRole};
use event::{spawn_event_reader, AppEvent};
use state::{AppState, ExplorerRow, Focus};
use status::{Mode, StatusBar};

/// Run the TUI application. Takes ownership of the Agent and a DB pool clone.
/// Blocks until the user quits.
pub async fn run(agent: Agent, pool: SqlitePool) -> anyhow::Result<()> {
    std::io::stdout().execute(EnterAlternateScreen)?;
    terminal::enable_raw_mode()?;

    let terminal = ratatui::init();
    let result = run_app(terminal, agent, pool).await;

    ratatui::restore();
    terminal::disable_raw_mode().ok();
    std::io::stdout().execute(LeaveAlternateScreen).ok();

    result
}

/// Inner loop, separated so we can restore the terminal even on error.
async fn run_app(
    mut terminal: DefaultTerminal,
    agent: Agent,
    pool: SqlitePool,
) -> anyhow::Result<()> {
    let mut state = AppState::new(pool);

    let (app_tx, mut app_rx) = mpsc::channel::<AppEvent>(256);
    spawn_event_reader(app_tx.clone());

    let (cmd_tx, mut cmd_rx) = mpsc::channel::<String>(16);
    let (agent_tx, mut agent_rx) = mpsc::channel::<AgentEvent>(256);

    // Forward agent events into the unified app channel
    let app_tx_for_agent = app_tx.clone();
    tokio::spawn(async move {
        while let Some(evt) = agent_rx.recv().await {
            if app_tx_for_agent.send(AppEvent::Agent(evt)).await.is_err() {
                break;
            }
        }
    });

    // Agent runner task
    tokio::spawn(async move {
        let mut agent = agent;
        while let Some(user_text) = cmd_rx.recv().await {
            if let Err(e) = agent.run_turn(&user_text, &agent_tx).await {
                agent_tx
                    .send(AgentEvent::Error(e.to_string()))
                    .await
                    .ok();
            }
            agent_tx.send(AgentEvent::TurnComplete).await.ok();
        }
    });

    // Main loop
    while !state.should_quit {
        terminal.draw(|frame| draw(frame, &state))?;

        let Some(event) = app_rx.recv().await else {
            break;
        };

        match event {
            AppEvent::Key(key) => {
                handle_key(key, &mut state, &cmd_tx, &app_tx);
            }

            AppEvent::Agent(agent_event) => {
                handle_agent_event(agent_event, &mut state);
                state.scroll_offset = 0;
            }

            AppEvent::ExplorerLoaded(rows) => {
                state.explorer.rows = rows;
                state.explorer.cursor = 0;
            }

            AppEvent::EntryContent(text) => {
                state.messages.push(ChatMessage {
                    role: ChatRole::System,
                    content: text,
                });
                state.scroll_offset = 0;
            }

            AppEvent::Resize(_, _) => {}
            AppEvent::Tick => {}
        }
    }

    Ok(())
}

// ── Drawing ──────────────────────────────────────────────────────────

fn draw(frame: &mut Frame, state: &AppState) {
    let area = frame.area();

    let filtered = commands::filter_commands(&state.palette.filter);
    let palette_visible = state.palette.visible && !filtered.is_empty();
    let palette_height = if palette_visible {
        std::cmp::min(filtered.len() as u16 + 2, 12)
    } else {
        0
    };

    // If explorer is visible, split horizontally: explorer (left) | chat area (right)
    let (explorer_area, main_area) = if state.explorer_visible {
        let h_chunks = Layout::horizontal([
            Constraint::Length(35),
            Constraint::Min(1),
        ])
        .split(area);
        (Some(h_chunks[0]), h_chunks[1])
    } else {
        (None, area)
    };

    // Right side: vertical stack of chat / [palette] / input / status
    let mut constraints = vec![Constraint::Min(1)]; // Chat
    let mut next_idx: usize = 1;

    let palette_idx = if palette_visible {
        constraints.push(Constraint::Length(palette_height));
        let idx = next_idx;
        next_idx += 1;
        Some(idx)
    } else {
        None
    };

    constraints.push(Constraint::Length(3)); // Input
    let input_idx = next_idx;
    next_idx += 1;

    constraints.push(Constraint::Length(3)); // Status
    let status_idx = next_idx;

    let chunks = Layout::vertical(constraints).split(main_area);

    // Chat
    frame.render_widget(
        ChatArea {
            messages: &state.messages,
            scroll_offset: state.scroll_offset,
        },
        chunks[0],
    );

    // Palette
    if let Some(idx) = palette_idx {
        frame.render_widget(
            palette::CommandPalette {
                state: &state.palette,
            },
            chunks[idx],
        );
    }

    // Explorer (left pane)
    if let Some(area) = explorer_area {
        frame.render_widget(
            explorer::ExplorerWidget {
                state: &state.explorer,
                focused: state.focus == Focus::Explorer,
            },
            area,
        );
    }

    // Input
    frame.render_widget(&state.text_input, chunks[input_idx]);

    // Status
    frame.render_widget(StatusBar { info: &state.status }, chunks[status_idx]);
}

// ── Key handling ─────────────────────────────────────────────────────

fn handle_key(
    key: KeyEvent,
    state: &mut AppState,
    cmd_tx: &mpsc::Sender<String>,
    app_tx: &mpsc::Sender<AppEvent>,
) {
    // Global bindings
    match (key.code, key.modifiers) {
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            if state.is_busy {
                state.messages.push(ChatMessage {
                    role: ChatRole::System,
                    content: "Cancelled.".into(),
                });
                state.is_busy = false;
                state.status.mode = Mode::Idle;
                input::set_busy(&mut state.text_input, false);
            } else if state.text_input.lines().join("").trim().is_empty() {
                state.should_quit = true;
            } else {
                state.text_input.select_all();
                state.text_input.cut();
            }
            return;
        }

        (KeyCode::Char('r'), KeyModifiers::CONTROL) => {
            toggle_explorer(state, app_tx);
            return;
        }

        _ => {}
    }

    // Focus dispatch
    match state.focus {
        Focus::Input => {
            handle_input_key(key, state, cmd_tx, app_tx);
            update_palette_visibility(state);
        }
        Focus::CommandPalette => handle_palette_key(key, state, app_tx),
        Focus::Explorer => handle_explorer_key(key, state, app_tx),
    }
}

fn handle_input_key(
    key: KeyEvent,
    state: &mut AppState,
    cmd_tx: &mpsc::Sender<String>,
    app_tx: &mpsc::Sender<AppEvent>,
) {
    match (key.code, key.modifiers) {
        (KeyCode::Esc, _) => {
            state.text_input.select_all();
            state.text_input.cut();
            state.palette.visible = false;
            state.palette.filter.clear();
            state.focus = Focus::Input;
        }

        // Tab: switch focus to explorer if it's open and input is empty
        (KeyCode::Tab, _) => {
            if state.explorer_visible
                && state.text_input.lines().join("").trim().is_empty()
            {
                state.focus = Focus::Explorer;
            } else {
                state.text_input.input(key);
            }
        }

        (KeyCode::Enter, KeyModifiers::NONE) => {
            if state.is_busy {
                return;
            }
            if let Some(user_text) = input::take_input(&mut state.text_input) {
                submit_input(user_text, state, cmd_tx, app_tx);
            }
        }

        _ => {
            state.text_input.input(key);
        }
    }
}

fn submit_input(
    user_text: String,
    state: &mut AppState,
    cmd_tx: &mpsc::Sender<String>,
    app_tx: &mpsc::Sender<AppEvent>,
) {
    state.palette.visible = false;
    state.palette.filter.clear();
    state.focus = Focus::Input;

    // Try local command first
    let mut trigger_explorer = false;
    match commands::execute(&user_text, state, &mut trigger_explorer) {
        commands::ExecResult::Handled => {
            if trigger_explorer {
                toggle_explorer(state, app_tx);
            }
            return;
        }
        commands::ExecResult::NotACommand => {}
    }

    // Send to LLM
    state.messages.push(ChatMessage {
        role: ChatRole::User,
        content: user_text.clone(),
    });
    state.scroll_offset = 0;
    state.is_busy = true;
    state.status.mode = Mode::Thinking;
    input::set_busy(&mut state.text_input, true);

    if cmd_tx.try_send(user_text).is_err() {
        state.messages.push(ChatMessage {
            role: ChatRole::Error,
            content: "Agent is not available.".into(),
        });
        state.is_busy = false;
        state.status.mode = Mode::Idle;
        input::set_busy(&mut state.text_input, false);
    }
}

fn update_palette_visibility(state: &mut AppState) {
    let text: String = state.text_input.lines().join("");
    if text.starts_with('/') && !text.contains('\n') {
        let filter = text[1..].to_string();
        let filtered = commands::filter_commands(&filter);
        state.palette.visible = !filtered.is_empty();
        state.palette.filter = filter;
        state.palette.selected_index = 0;
        if state.palette.visible {
            state.focus = Focus::CommandPalette;
        }
    } else {
        state.palette.visible = false;
        state.palette.filter.clear();
        if state.focus == Focus::CommandPalette {
            state.focus = Focus::Input;
        }
    }
}

fn handle_palette_key(
    key: KeyEvent,
    state: &mut AppState,
    app_tx: &mpsc::Sender<AppEvent>,
) {
    let filtered = commands::filter_commands(&state.palette.filter);
    let count = filtered.len();

    match (key.code, key.modifiers) {
        (KeyCode::Up, KeyModifiers::NONE) => {
            if count > 0 {
                state.palette.selected_index =
                    (state.palette.selected_index + count - 1) % count;
            }
        }

        (KeyCode::Down, KeyModifiers::NONE) => {
            if count > 0 {
                state.palette.selected_index =
                    (state.palette.selected_index + 1) % count;
            }
        }

        (KeyCode::Enter, KeyModifiers::NONE) | (KeyCode::Tab, _) => {
            if count > 0 {
                let idx = std::cmp::min(state.palette.selected_index, count - 1);
                let name = filtered[idx].name;
                let command_text = format!("/{}", name);

                state.text_input.select_all();
                state.text_input.cut();

                let mut trigger_explorer = false;
                commands::execute(&command_text, state, &mut trigger_explorer);
                if trigger_explorer {
                    toggle_explorer(state, app_tx);
                }

                state.palette.visible = false;
                state.palette.filter.clear();
                state.focus = Focus::Input;
            }
        }

        (KeyCode::Esc, _) => {
            state.text_input.select_all();
            state.text_input.cut();
            state.palette.visible = false;
            state.palette.filter.clear();
            state.focus = Focus::Input;
        }

        _ => {
            state.text_input.input(key);
            update_palette_visibility(state);
        }
    }
}

fn handle_explorer_key(
    key: KeyEvent,
    state: &mut AppState,
    app_tx: &mpsc::Sender<AppEvent>,
) {
    let count = state.explorer.rows.len();

    match (key.code, key.modifiers) {
        (KeyCode::Up, KeyModifiers::NONE) => {
            if count > 0 && state.explorer.cursor > 0 {
                state.explorer.cursor -= 1;
            }
        }

        (KeyCode::Down, KeyModifiers::NONE) => {
            if count > 0 && state.explorer.cursor < count - 1 {
                state.explorer.cursor += 1;
            }
        }

        // Enter: read the selected entry's content into chat
        (KeyCode::Enter, KeyModifiers::NONE) => {
            if count > 0 {
                let row = &state.explorer.rows[state.explorer.cursor];
                if let ExplorerRow::Entry { id, .. } = row {
                    let entry_id = *id;
                    let pool = state.pool.clone();
                    let tx = app_tx.clone();
                    tokio::spawn(async move {
                        match crate::db::entries::get_entry(&pool, entry_id).await {
                            Ok(Some(entry)) => {
                                let mut text = format!("**{}**", entry.title);
                                if let Some(etype) = &entry.entry_type {
                                    text.push_str(&format!("  [{:?}]", etype));
                                }
                                text.push_str(&format!("\n\n{}", entry.content));
                                if !entry.additional_notes.is_empty() {
                                    text.push_str(&format!("\n\n---\n{}", entry.additional_notes));
                                }
                                tx.send(AppEvent::Agent(AgentEvent::TextDelta(
                                    "\n".to_string(),
                                )))
                                .await
                                .ok();
                                // Use a system message to show entry content
                                // We'll send it as a special event
                                tx.send(AppEvent::EntryContent(text)).await.ok();
                            }
                            Ok(None) => {
                                tx.send(AppEvent::Agent(AgentEvent::Error(
                                    format!("Entry {} not found", entry_id),
                                )))
                                .await
                                .ok();
                            }
                            Err(e) => {
                                tx.send(AppEvent::Agent(AgentEvent::Error(
                                    format!("Failed to read entry: {}", e),
                                )))
                                .await
                                .ok();
                            }
                        }
                    });
                }
            }
        }

        // Tab: switch focus back to input (keep explorer open)
        (KeyCode::Tab, _) | (KeyCode::Esc, _) => {
            state.focus = Focus::Input;
        }

        _ => {}
    }
}

// ── Explorer toggle ──────────────────────────────────────────────────

/// Toggle the explorer panel and trigger async DB load.
fn toggle_explorer(state: &mut AppState, app_tx: &mpsc::Sender<AppEvent>) {
    state.explorer_visible = !state.explorer_visible;
    if state.explorer_visible {
        state.focus = Focus::Explorer;
        let pool = state.pool.clone();
        let tx = app_tx.clone();
        tokio::spawn(async move {
            match crate::db::explorer::load_explorer_data(&pool).await {
                Ok((topics, entries)) => {
                    let rows = build_explorer_rows(&topics, &entries);
                    tx.send(AppEvent::ExplorerLoaded(rows)).await.ok();
                }
                Err(e) => {
                    tx.send(AppEvent::Agent(AgentEvent::Error(
                        format!("Failed to load explorer: {}", e),
                    )))
                    .await
                    .ok();
                }
            }
        });
    } else {
        state.focus = Focus::Input;
    }
}

/// Build a flat list of ExplorerRows from the DB data, with depth-first tree ordering.
fn build_explorer_rows(
    topics: &[crate::db::explorer::TopicWithCount],
    entries: &[crate::db::explorer::EntryRow],
) -> Vec<ExplorerRow> {
    use std::collections::HashMap;

    // Index children by parent_id
    let mut children_map: HashMap<Option<i64>, Vec<&crate::db::explorer::TopicWithCount>> =
        HashMap::new();
    for t in topics {
        children_map.entry(t.parent_id).or_default().push(t);
    }

    // Index entries by topic_id
    let mut entries_map: HashMap<i64, Vec<&crate::db::explorer::EntryRow>> = HashMap::new();
    for e in entries {
        entries_map.entry(e.topic_id).or_default().push(e);
    }

    let mut rows = Vec::new();

    // DFS from roots (parent_id = None)
    fn walk(
        parent_id: Option<i64>,
        depth: usize,
        children_map: &HashMap<Option<i64>, Vec<&crate::db::explorer::TopicWithCount>>,
        entries_map: &HashMap<i64, Vec<&crate::db::explorer::EntryRow>>,
        rows: &mut Vec<ExplorerRow>,
    ) {
        let Some(children) = children_map.get(&parent_id) else {
            return;
        };
        for topic in children {
            rows.push(ExplorerRow::Topic {
                id: topic.id,
                name: topic.name.clone(),
                depth,
                entry_count: topic.entry_count,
            });

            // Add entries under this topic
            if let Some(topic_entries) = entries_map.get(&topic.id) {
                for entry in topic_entries {
                    rows.push(ExplorerRow::Entry {
                        id: entry.id,
                        title: entry.title.clone(),
                        entry_type: entry.entry_type.clone(),
                        depth: depth + 1,
                    });
                }
            }

            // Recurse into child topics
            walk(Some(topic.id), depth + 1, children_map, entries_map, rows);
        }
    }

    walk(None, 0, &children_map, &entries_map, &mut rows);
    rows
}

// ── Agent events ─────────────────────────────────────────────────────

fn handle_agent_event(event: AgentEvent, state: &mut AppState) {
    match event {
        AgentEvent::TextDelta(text) => {
            if let Some(last) = state.messages.last_mut() {
                if last.role == ChatRole::Assistant {
                    last.content.push_str(&text);
                    return;
                }
            }
            state.messages.push(ChatMessage {
                role: ChatRole::Assistant,
                content: text,
            });
        }

        AgentEvent::ToolCallStart { name } => {
            state.messages.push(ChatMessage {
                role: ChatRole::ToolCall,
                content: format!("⚡ {}", name),
            });
        }

        AgentEvent::ToolCallResult { name, result } => {
            if let Some(last) = state.messages.last_mut() {
                if last.role == ChatRole::ToolCall && last.content.contains(&name) {
                    let display = if result.len() > 200 {
                        format!("{}...", &result[..200])
                    } else {
                        result
                    };
                    last.content = format!("✓ {} — {}", name, display);
                    return;
                }
            }
            state.messages.push(ChatMessage {
                role: ChatRole::ToolCall,
                content: format!("✓ {} — done", name),
            });
        }

        AgentEvent::TurnComplete => {
            state.is_busy = false;
            state.status.mode = Mode::Idle;
            input::set_busy(&mut state.text_input, false);
        }

        AgentEvent::Error(msg) => {
            state.messages.push(ChatMessage {
                role: ChatRole::Error,
                content: msg,
            });
            state.is_busy = false;
            state.status.mode = Mode::Idle;
            input::set_busy(&mut state.text_input, false);
        }
    }
}
