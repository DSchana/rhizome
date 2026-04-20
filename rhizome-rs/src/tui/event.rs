//! Unified event stream for the TUI.
//!
//! Merges three event sources into a single channel:
//! - Terminal events (key presses, resize) from crossterm
//! - Agent events from the agent task
//! - Periodic ticks for animations (spinner, etc.)

use std::time::Duration;

use crossterm::event::{self as ct, KeyEvent};
use tokio::sync::mpsc;

use crate::agent::AgentEvent;
use super::state::ExplorerRow;

/// Every event the main loop can receive.
#[derive(Debug)]
pub enum AppEvent {
    /// A key press from the terminal
    Key(KeyEvent),
    /// Terminal was resized
    Resize(u16, u16),
    /// An event from the agent (text delta, tool call, turn complete, etc.)
    Agent(AgentEvent),
    /// Explorer data loaded from the database (topics + entries as flat rows)
    ExplorerLoaded(Vec<ExplorerRow>),
    /// Entry content loaded for display in chat
    EntryContent(String),
    /// Periodic tick for animations (~10 Hz)
    Tick,
}

/// Spawn a background task that reads terminal events and ticks,
/// forwarding them as `AppEvent`s.
pub fn spawn_event_reader(app_tx: mpsc::Sender<AppEvent>) {
    let tick_rate = Duration::from_millis(100);

    tokio::spawn(async move {
        loop {
            let has_event = tokio::task::spawn_blocking(move || {
                ct::poll(tick_rate).unwrap_or(false)
            })
            .await
            .unwrap_or(false);

            if has_event {
                if let Ok(event) = ct::read() {
                    let app_event = match event {
                        ct::Event::Key(key) => Some(AppEvent::Key(key)),
                        ct::Event::Resize(w, h) => Some(AppEvent::Resize(w, h)),
                        _ => None,
                    };
                    if let Some(e) = app_event {
                        if app_tx.send(e).await.is_err() {
                            return;
                        }
                    }
                }
            } else {
                if app_tx.send(AppEvent::Tick).await.is_err() {
                    return;
                }
            }
        }
    });
}
