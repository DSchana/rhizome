//! App struct — owns all tabs and global state.
//!
//! Each tab gets its own agent task and command channel.
//! The App coordinates tab lifecycle and routes events.

use sqlx::SqlitePool;
use tokio::sync::mpsc;

use crate::agent::{Agent, AgentEvent};
use crate::tui::event::AppEvent;
use crate::tui::tab::TabState;

/// Top-level application state.
pub struct App {
    pub tabs: Vec<TabState>,
    pub active_tab: usize,
    pub should_quit: bool,
    pub tab_counter: usize,

    // Shared resources for spawning new agent tasks
    api_key: String,
    pool: SqlitePool,
    app_tx: mpsc::Sender<AppEvent>,
}

impl App {
    pub fn new(
        api_key: String,
        pool: SqlitePool,
        app_tx: mpsc::Sender<AppEvent>,
    ) -> Self {
        Self {
            tabs: Vec::new(),
            active_tab: 0,
            should_quit: false,
            tab_counter: 0,
            api_key,
            pool,
            app_tx,
        }
    }

    /// Create a new tab with its own agent task. Returns the tab index.
    pub fn new_tab(&mut self) -> usize {
        self.tab_counter += 1;
        let name = format!("Session {}", self.tab_counter);

        // Channel: main loop sends user text to the agent task
        let (cmd_tx, cmd_rx) = mpsc::channel::<String>(16);

        // Channel: agent task sends events back
        let (agent_tx, agent_rx) = mpsc::channel::<AgentEvent>(256);

        // Forward agent events into the unified app channel, tagged with tab index
        let tab_idx = self.tabs.len();
        let app_tx = self.app_tx.clone();
        tokio::spawn(async move {
            let mut agent_rx = agent_rx;
            while let Some(evt) = agent_rx.recv().await {
                if app_tx
                    .send(AppEvent::Agent(tab_idx, evt))
                    .await
                    .is_err()
                {
                    break;
                }
            }
        });

        // Spawn the agent runner task
        let api_key = self.api_key.clone();
        let pool = self.pool.clone();
        tokio::spawn(async move {
            let mut agent = Agent::new(api_key, pool);
            let mut cmd_rx = cmd_rx;
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

        let tab = TabState::new(name, cmd_tx);
        self.tabs.push(tab);
        let idx = self.tabs.len() - 1;
        self.active_tab = idx;
        idx
    }

    /// Close the active tab. Refuses to close the last tab.
    pub fn close_active_tab(&mut self) {
        if self.tabs.len() <= 1 {
            return;
        }
        self.tabs.remove(self.active_tab);
        if self.active_tab >= self.tabs.len() {
            self.active_tab = self.tabs.len() - 1;
        }
    }

    /// Switch to the next tab (wrapping).
    pub fn next_tab(&mut self) {
        if self.tabs.len() > 1 {
            self.active_tab = (self.active_tab + 1) % self.tabs.len();
        }
    }

    /// Switch to the previous tab (wrapping).
    pub fn prev_tab(&mut self) {
        if self.tabs.len() > 1 {
            self.active_tab = (self.active_tab + self.tabs.len() - 1) % self.tabs.len();
        }
    }

    /// Get a reference to the active tab state.
    pub fn tab(&self) -> &TabState {
        &self.tabs[self.active_tab]
    }

    /// Get a mutable reference to the active tab state.
    pub fn tab_mut(&mut self) -> &mut TabState {
        &mut self.tabs[self.active_tab]
    }

    /// Get the DB pool (for sidebar/explorer queries).
    pub fn pool(&self) -> &SqlitePool {
        &self.pool
    }
}
