//! Anthropic HTTP client with SSE streaming

use futures::StreamExt;
use tokio::sync::mpsc;

use crate::agent::types::{ MessageRequest, StreamEvent };

pub struct AnthropicClient {
    http: reqwest::Client,
    api_key: String,
    pub model: String,
}

impl AnthropicClient {
    pub fn new(api_key: String, model: &str) -> Self {
        Self {
            http: reqwest::Client::new(),
            api_key,
            model: model.to_string(),
        }
    }

    /// Send a streaming Messages API request
    ///
    /// Reutnrs a channel receiver that yields parsed SSE events.
    /// A background task reads the byte stream, splits SSE frames,
    /// and deserializes each `data:` line into a `StreamEvent`.
    pub async fn stream_messages(
        &self,
        request: &MessageRequest,
    ) -> anyhow::Result<mpsc::Receiver<StreamEvent>> {
        let response = self
            .http
            .post("https://api.anthropic.com/v1/messages")
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", "2023-06-01")
            .header("content-type", "application/json")
            .json(request)
            .send()
            .await?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Anthropic API error {}: {}", status, body);
        }

        let (tx, rx) = mpsc::channel(64);
        let stream = response.bytes_stream();

        // Spawn a background task to parse the SSE stream
        tokio::spawn(async move {
            let mut buffer = String::new();
            let mut data_line = String::new();

            // Pin the stream so we can call .next() on it
            tokio::pin!(stream);

            while let Some(chunk) = stream.next().await {
                let chunk = match chunk {
                    Ok(c) => c,
                    Err(_) => break,
                };
                buffer.push_str(&String::from_utf8_lossy(&chunk));

                // Process all complete lines in the buffer
                // TODO(dilpreet): This can probably be more efficient
                while let Some(pos) = buffer.find('\n') {
                    let line = buffer[..pos].trim_end_matches('\r').to_string();
                    buffer = buffer[pos + 1..].to_string();

                    if let Some(data) = line.strip_prefix("data: ") {
                        data_line = data.to_string();
                    } else if line.is_empty() && !data_line.is_empty() {
                        // Blank line = end of SSE event, parse and accumulate data

                        if let Ok(event) = serde_json::from_str::<StreamEvent>(&data_line) {
                            if tx.send(event).await.is_err() {
                                return;  // Receiver dropped
                            }
                        }
                        data_line.clear();
                    }
                }
            }
        });

        Ok(rx)
    }
}

