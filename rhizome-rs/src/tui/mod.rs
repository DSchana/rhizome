//! TUI application — ratatui main loop, layout, and state management.
//!
//! Architecture:
//! - The agent owns its own tokio task, receiving user text via a command channel.
//! - The agent sends AgentEvents to the TUI via a second channel.
//! - A third channel merges terminal events (keys, resize) with agent events
//!   and ticks into a single AppEvent stream for the main loop.

pub mod chat;
pub mod event;
pub mod input;
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
use tokio::sync::mpsc;
use tui_textarea::TextArea;

use crate::agent::{Agent, AgentEvent};
use chat::{ChatArea, ChatMessage, ChatRole};
use event::{spawn_event_reader, AppEvent};
use status::{StatusBar, StatusInfo};

/// Run the TUI application. Takes ownership of the Agent.
/// Blocks until the user quits.
pub async fn run(agent: Agent) -> anyhow::Result<()> {
    // Enter raw mode and alternate screen
    std::io::stdout().execute(EnterAlternateScreen)?;
    terminal::enable_raw_mode()?;

    let terminal = ratatui::init();
    let result = run_app(terminal, agent).await;

    // Restore terminal no matter what
    ratatui::restore();
    terminal::disable_raw_mode().ok();
    std::io::stdout().execute(LeaveAlternateScreen).ok();

    result
}

/// Inner loop, separated so we can restore the terminal even on error.
async fn run_app(mut terminal: DefaultTerminal, agent: Agent) -> anyhow::Result<()> {
    let mut messages: Vec<ChatMessage> = Vec::new();
    let mut text_input: TextArea<'static> = input::new_input();
    let mut is_busy = false;
    let mut should_quit = false;
    let mut scroll_offset: u16 = 0; // 0 = auto-scroll to bottom

    // Channel for all app events (terminal + agent + tick)
    let (app_tx, mut app_rx) = mpsc::channel::<AppEvent>(256);

    // Spawn the terminal event reader (keys, resize, ticks)
    spawn_event_reader(app_tx.clone());

    // Channel: main loop sends user text to the agent task
    let (cmd_tx, mut cmd_rx) = mpsc::channel::<String>(16);

    // Channel: agent task sends events back to the main loop
    let (agent_tx, mut agent_rx) = mpsc::channel::<AgentEvent>(256);

    // Spawn a task that forwards agent events into the unified app channel
    let app_tx_for_agent = app_tx.clone();
    tokio::spawn(async move {
        while let Some(evt) = agent_rx.recv().await {
            if app_tx_for_agent
                .send(AppEvent::Agent(evt))
                .await
                .is_err()
            {
                break;
            }
        }
    });

    // Spawn the agent runner task, it owns the Agent and processes
    // one command at a time. No mutex needed since it's single-threaded.
    tokio::spawn(async move {
        let mut agent = agent;
        while let Some(user_text) = cmd_rx.recv().await {
            if let Err(e) = agent.run_turn(&user_text, &agent_tx).await {
                agent_tx
                    .send(AgentEvent::Error(e.to_string()))
                    .await
                    .ok();
            }
            // Always signal turn complete so the UI unlocks
            agent_tx.send(AgentEvent::TurnComplete).await.ok();
        }
    });

    // Welcome message
    messages.push(ChatMessage {
        role: ChatRole::System,
        content: "Rhizome — type a message to chat. Ctrl+C to quit.".into(),
    });

    // Main loop
    while !should_quit {
        // Draw
        terminal.draw(|frame| draw(frame, &messages, &text_input, is_busy, scroll_offset))?;

        // Wait for next event
        let Some(event) = app_rx.recv().await else {
            break; // all senders dropped
        };

        match event {
            AppEvent::Key(key) => {
                handle_key(
                    key,
                    &mut text_input,
                    &mut messages,
                    &mut is_busy,
                    &mut should_quit,
                    &mut scroll_offset,
                    &cmd_tx,
                );
            }

            AppEvent::Agent(agent_event) => {
                handle_agent_event(agent_event, &mut messages, &mut is_busy, &mut text_input);
                // Reset scroll to auto on new agent content
                scroll_offset = 0;
            }

            AppEvent::Resize(_, _) => {
                // Ratatui handles resize automatically on next draw
            }

            AppEvent::Tick => {
                // Could drive animations here (spinner, etc.)
                // For now, just triggers a redraw
            }
        }
    }

    Ok(())
}

/// Draw the full UI layout.
fn draw(
    frame: &mut Frame,
    messages: &[ChatMessage],
    text_input: &TextArea<'_>,
    is_busy: bool,
    scroll_offset: u16,
) {
    let area = frame.area();

    // Three-region vertical split:
    //   [0] Message area — takes all remaining space
    //   [1] Input bar    — 3 lines
    //   [2] Status bar   — 1 line
    let chunks = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(3),
        Constraint::Length(1),
    ])
    .split(area);

    // Message area
    let chat = ChatArea {
        messages,
        scroll_offset,
    };
    frame.render_widget(chat, chunks[0]);

    // Input bar
    frame.render_widget(text_input, chunks[1]);

    // Status bar
    let status = StatusBar {
        info: &StatusInfo { is_busy },
    };
    frame.render_widget(status, chunks[2]);
}

/// Handle a key press event.
fn handle_key(
    key: KeyEvent,
    text_input: &mut TextArea<'static>,
    messages: &mut Vec<ChatMessage>,
    is_busy: &mut bool,
    should_quit: &mut bool,
    scroll_offset: &mut u16,
    cmd_tx: &mpsc::Sender<String>,
) {
    match (key.code, key.modifiers) {
        // Ctrl+C: cancel if busy, quit if idle and input is empty
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            if *is_busy {
                // TODO(dilpreet): cancel the agent task (needs a CancellationToken)
                messages.push(ChatMessage {
                    role: ChatRole::System,
                    content: "Cancelled.".into(),
                });
                *is_busy = false;
                input::set_busy(text_input, false);
            } else if text_input.lines().join("").trim().is_empty() {
                *should_quit = true;
            } else {
                // Clear input on first Ctrl+C when there's text
                text_input.select_all();
                text_input.cut();
            }
        }

        // Escape: clear input
        (KeyCode::Esc, _) => {
            text_input.select_all();
            text_input.cut();
        }

        // Enter: submit if not busy
        (KeyCode::Enter, KeyModifiers::NONE) => {
            if *is_busy {
                return;
            }
            if let Some(user_text) = input::take_input(text_input) {
                // Add user message to chat
                messages.push(ChatMessage {
                    role: ChatRole::User,
                    content: user_text.clone(),
                });
                *scroll_offset = 0;

                // Mark busy and send to agent task
                *is_busy = true;
                input::set_busy(text_input, true);

                // Non-blocking send — the agent task picks it up
                if cmd_tx.try_send(user_text).is_err() {
                    messages.push(ChatMessage {
                        role: ChatRole::Error,
                        content: "Agent is not available.".into(),
                    });
                    *is_busy = false;
                    input::set_busy(text_input, false);
                }
            }
        }

        // All other keys: forward to the textarea
        _ => {
            text_input.input(key);
        }
    }
}

/// Handle an event from the agent.
fn handle_agent_event(
    event: AgentEvent,
    messages: &mut Vec<ChatMessage>,
    is_busy: &mut bool,
    text_input: &mut TextArea<'static>,
) {
    match event {
        AgentEvent::TextDelta(text) => {
            // Append to the last assistant message, or start a new one
            if let Some(last) = messages.last_mut() {
                if last.role == ChatRole::Assistant {
                    last.content.push_str(&text);
                    return;
                }
            }
            // Start a new assistant message
            messages.push(ChatMessage {
                role: ChatRole::Assistant,
                content: text,
            });
        }

        AgentEvent::ToolCallStart { name } => {
            messages.push(ChatMessage {
                role: ChatRole::ToolCall,
                content: format!("⚡ {}", name),
            });
        }

        AgentEvent::ToolCallResult { name, result } => {
            // Update the last tool call message, or add a new one
            if let Some(last) = messages.last_mut() {
                if last.role == ChatRole::ToolCall && last.content.contains(&name) {
                    // Truncate long results for display
                    let display = if result.len() > 200 {
                        format!("{}...", &result[..200])
                    } else {
                        result
                    };
                    last.content = format!("✓ {} — {}", name, display);
                    return;
                }
            }
            messages.push(ChatMessage {
                role: ChatRole::ToolCall,
                content: format!("✓ {} — done", name),
            });
        }

        AgentEvent::TurnComplete => {
            *is_busy = false;
            input::set_busy(text_input, false);
        }

        AgentEvent::Error(msg) => {
            messages.push(ChatMessage {
                role: ChatRole::Error,
                content: msg,
            });
            *is_busy = false;
            input::set_busy(text_input, false);
        }
    }
}
