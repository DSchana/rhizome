//! Agent: LLM conversation loop with tool calling

pub mod client;
pub mod tools;
pub mod types;

use std::io::Write;

use sqlx::SqlitePool;

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

/// One in-progress content block being accumulated from stream events
enum AccumulatingBlock {
    Text(String),
    ToolUse {
        id: String,
        name: String,
        json: String,
    },
}

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
            // Bug fix: was `history, Vec::new()` (comma instead of colon)
            history: Vec::new(),
        }
    }

    /// Run one conversation turn: send user text, stream the response,
    /// execute any tool calls, and loop until the LLM returns pure text.
    pub async fn run_turn(&mut self, user_text: &str) -> anyhow::Result<()> {
        // Add user message to history
        self.history.push(Message {
            role: Role::User,
            content: vec![ContentBlock::Text {
                text: user_text.to_string(),
            }],
        });

        // Loop: Call API -> stream response -> execute tools -> call API again.
        // The LLM may call multiple tools before returning a final text response,
        // so we keep looping until we get a response with no tool_use blocks.
        loop {
            // Bug fix: was `message:` (singular), field is `messages` (plural)
            let req = MessageRequest {
                model: self.client.model.clone(),
                max_tokens: 8096,
                system: SYSTEM_PROMPT.to_string(),
                messages: self.history.clone(),
                tools: tools::definitions(),
                stream: true,
            };

            let mut rx = self.client.stream_messages(&req).await?;

            // Accumulate content blocks from the stream.
            // Each block starts with ContentBlockStart and grows via ContentBlockDelta.
            let mut blocks: Vec<AccumulatingBlock> = Vec::new();

            while let Some(event) = rx.recv().await {
                match event {
                    StreamEvent::ContentBlockStart { content_block, .. } => {
                        match content_block {
                            ContentBlockInfo::Text { text } => {
                                // Print the initial text (usually empty, but included for safety)
                                if !text.is_empty() {
                                    print!("{}", text);
                                    std::io::stdout().flush().ok();
                                }
                                blocks.push(AccumulatingBlock::Text(text));
                            }
                            ContentBlockInfo::ToolUse { id, name } => {
                                // Tool calls accumulate JSON input via InputJsonDelta events
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
                                    // Stream text directly to stdout as it arrives
                                    print!("{}", text);
                                    std::io::stdout().flush().ok();
                                    s.push_str(&text);
                                }
                                (
                                    AccumulatingBlock::ToolUse { json, .. },
                                    Delta::InputJsonDelta { partial_json },
                                ) => {
                                    // Accumulate JSON input for the tool call
                                    json.push_str(&partial_json);
                                }
                                _ => {}
                            }
                        }
                    }

                    StreamEvent::Error { error } => {
                        anyhow::bail!(
                            "API error ({}): {}",
                            error.error_type,
                            error.message
                        );
                    }

                    // MessageStop, MessageDelta, ContentBlockStop, Ping -- nothing to do
                    _ => {}
                }
            }

            // Convert the accumulated blocks into typed ContentBlocks for history.
            // While doing so, note whether any ToolUse blocks appeared -- if none did,
            // the LLM is done and we can break the loop.
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
                        // Parse the accumulated JSON; fall back to empty object on bad JSON.
                        // Default must be `{}` not `null` — the API requires input to be a dict.
                        let input: serde_json::Value =
                            serde_json::from_str(&json).unwrap_or(serde_json::json!({}));
                        content_blocks.push(ContentBlock::ToolUse { id, name, input });
                    }
                }
            }

            // Push the assistant's full response into history
            self.history.push(Message {
                role: Role::Assistant,
                content: content_blocks.clone(),
            });

            // If the LLM returned no tool calls, it's done speaking for this turn
            if !has_tool_use {
                println!(); // final newline after the streamed text
                break;
            }

            // Dispatch every tool call and collect the results.
            // Errors are returned as plain text -- the LLM sees them and can adapt.
            let mut tool_results: Vec<ContentBlock> = Vec::new();
            for block in &content_blocks {
                if let ContentBlock::ToolUse { id, name, input } = block {
                    let result = tools::dispatch(&self.pool, name, input.clone()).await;
                    tool_results.push(ContentBlock::ToolResult {
                        tool_use_id: id.clone(),
                        content: result,
                    });
                }
            }

            // Feed tool results back as a user message, then loop to call the API again
            self.history.push(Message {
                role: Role::User,
                content: tool_results,
            });
        }

        Ok(())
    }
}
