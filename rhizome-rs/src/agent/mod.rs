//! Agent: LLM conversation loop with tool calling.
//!
//! The agent sends structured `AgentEvent`s over a channel rather than
//! printing to stdout, so any frontend (TUI, CLI, tests) can consume them.

pub mod client;
pub mod tools;
pub mod types;

use sqlx::SqlitePool;
use tokio::sync::mpsc;

use client::AnthropicClient;
use types::{
    ContentBlock,
    ContentBlockInfo,
    Delta,
    Message,
    MessageRequest,
    Role,
    StreamEvent,
};

const SYSTEM_PROMPT: &str = "\
You are a knowledge management assistant connected to a SQLite database of topics \
and knowledge entries organized in a tree structure.

Use the provided tools to help the user explore, search, and add to their \
knowledge base. When creating entries, use clear and concise content. \
Format your responses using markdown.";

// ── Events emitted by the agent ──────────────────────────────────────

/// Structured events sent from the agent to the UI during a turn.
#[derive(Debug, Clone)]
pub enum AgentEvent {
    /// A chunk of streaming text from the LLM
    TextDelta(String),
    /// The LLM is calling a tool (sent before dispatch)
    ToolCallStart { name: String },
    /// A tool call finished (sent after dispatch)
    ToolCallResult { name: String, result: String },
    /// The full turn completed — no more events for this turn
    TurnComplete,
    /// A non-fatal error occurred
    Error(String),
}

// ── Accumulator for in-flight content blocks ─────────────────────────

/// One in-progress content block being assembled from stream events
enum AccumulatingBlock {
    Text(String),
    ToolUse {
        id: String,
        name: String,
        json: String,
    },
}

// ── Agent ────────────────────────────────────────────────────────────

pub struct Agent {
    client: AnthropicClient,
    pool: SqlitePool,
    history: Vec<Message>,
}

impl Agent {
    pub fn new(api_key: String, pool: SqlitePool) -> Self {
        Self {
            client: AnthropicClient::new(api_key, "claude-sonnet-4-20250514"),
            pool,
            history: Vec::new(),
        }
    }

    /// Run one conversation turn.
    ///
    /// Sends `AgentEvent`s over `tx` as the LLM streams its response.
    /// Loops internally when the LLM makes tool calls — the caller just
    /// keeps consuming events until it receives `TurnComplete`.
    pub async fn run_turn(
        &mut self,
        user_text: &str,
        tx: &mpsc::Sender<AgentEvent>,
    ) -> anyhow::Result<()> {
        // Add user message to history
        self.history.push(Message {
            role: Role::User,
            content: vec![ContentBlock::Text {
                text: user_text.to_string(),
            }],
        });

        loop {
            let req = MessageRequest {
                model: self.client.model.clone(),
                max_tokens: 8096,
                system: SYSTEM_PROMPT.to_string(),
                messages: self.history.clone(),
                tools: tools::definitions(),
                stream: true,
            };

            let mut rx = self.client.stream_messages(&req).await?;

            // Accumulate content blocks from the stream
            let mut blocks: Vec<AccumulatingBlock> = Vec::new();

            while let Some(event) = rx.recv().await {
                match event {
                    StreamEvent::ContentBlockStart { content_block, .. } => {
                        match content_block {
                            ContentBlockInfo::Text { text } => {
                                if !text.is_empty() {
                                    tx.send(AgentEvent::TextDelta(text.clone()))
                                        .await
                                        .ok();
                                }
                                blocks.push(AccumulatingBlock::Text(text));
                            }
                            ContentBlockInfo::ToolUse { id, name } => {
                                blocks.push(AccumulatingBlock::ToolUse {
                                    id,
                                    name,
                                    json: String::new(),
                                });
                            }
                        }
                    }

                    StreamEvent::ContentBlockDelta { index, delta } => {
                        if let Some(block) = blocks.get_mut(index) {
                            match (block, delta) {
                                (
                                    AccumulatingBlock::Text(s),
                                    Delta::TextDelta { text },
                                ) => {
                                    tx.send(AgentEvent::TextDelta(text.clone()))
                                        .await
                                        .ok();
                                    s.push_str(&text);
                                }
                                (
                                    AccumulatingBlock::ToolUse { json, .. },
                                    Delta::InputJsonDelta { partial_json },
                                ) => {
                                    json.push_str(&partial_json);
                                }
                                _ => {}
                            }
                        }
                    }

                    StreamEvent::Error { error } => {
                        let msg = format!(
                            "API error ({}): {}",
                            error.error_type, error.message
                        );
                        tx.send(AgentEvent::Error(msg.clone())).await.ok();
                        anyhow::bail!(msg);
                    }

                    _ => {}
                }
            }

            // Convert accumulated blocks into ContentBlocks for history
            let mut content_blocks: Vec<ContentBlock> = Vec::new();
            let mut has_tool_use = false;

            for block in blocks {
                match block {
                    AccumulatingBlock::Text(text) => {
                        if !text.is_empty() {
                            content_blocks.push(ContentBlock::Text { text });
                        }
                    }
                    AccumulatingBlock::ToolUse { id, name, json } => {
                        has_tool_use = true;
                        let input: serde_json::Value =
                            serde_json::from_str(&json).unwrap_or(serde_json::json!({}));
                        content_blocks.push(ContentBlock::ToolUse { id, name, input });
                    }
                }
            }

            // Push assistant response into history
            self.history.push(Message {
                role: Role::Assistant,
                content: content_blocks.clone(),
            });

            // No tool calls — turn is done
            if !has_tool_use {
                tx.send(AgentEvent::TurnComplete).await.ok();
                break;
            }

            // Dispatch tool calls, notify the UI for each
            let mut tool_results: Vec<ContentBlock> = Vec::new();
            for block in &content_blocks {
                if let ContentBlock::ToolUse { id, name, input } = block {
                    tx.send(AgentEvent::ToolCallStart {
                        name: name.clone(),
                    })
                    .await
                    .ok();

                    let result = tools::dispatch(&self.pool, name, input.clone()).await;

                    tx.send(AgentEvent::ToolCallResult {
                        name: name.clone(),
                        result: result.clone(),
                    })
                    .await
                    .ok();

                    tool_results.push(ContentBlock::ToolResult {
                        tool_use_id: id.clone(),
                        content: result,
                    });
                }
            }

            // Feed tool results back, loop to call the API again
            self.history.push(Message {
                role: Role::User,
                content: tool_results,
            });
        }

        Ok(())
    }
}
