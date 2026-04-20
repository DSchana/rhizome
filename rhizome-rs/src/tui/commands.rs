//! Static command registry for slash commands with local execution.

use super::chat::{ChatMessage, ChatRole};
use super::state::AppState;

/// A single command definition.
pub struct CommandDef {
    pub name: &'static str,
    pub description: &'static str,
}

/// All available slash commands.
const COMMANDS: &[CommandDef] = &[
    CommandDef {
        name: "clear",
        description: "Clear chat messages",
    },
    CommandDef {
        name: "help",
        description: "Show available commands and usage",
    },
    CommandDef {
        name: "quit",
        description: "Quit the application",
    },
    CommandDef {
        name: "explore",
        description: "Toggle explorer panel (topics & entries)",
    },
];

/// Return all commands whose name starts with `prefix`.
pub fn filter_commands(prefix: &str) -> Vec<&'static CommandDef> {
    COMMANDS
        .iter()
        .filter(|cmd| cmd.name.starts_with(prefix))
        .collect()
}

/// Try to parse input as a slash command. Returns the command name and args if it is one.
pub fn parse_command(input: &str) -> Option<(&str, &str)> {
    let trimmed = input.trim();
    if !trimmed.starts_with('/') {
        return None;
    }
    let without_slash = &trimmed[1..];
    let (name, args) = match without_slash.find(' ') {
        Some(pos) => (&without_slash[..pos], without_slash[pos + 1..].trim()),
        None => (without_slash, ""),
    };
    // Only match known commands
    if COMMANDS.iter().any(|c| c.name == name) {
        Some((name, args))
    } else {
        None
    }
}

/// Result of executing a command locally.
pub enum ExecResult {
    /// Command was handled locally, don't send to LLM
    Handled,
    /// Not a command, forward to LLM as normal
    NotACommand,
}

/// Execute a slash command locally. Returns whether it was handled.
pub fn execute(
    input: &str,
    state: &mut AppState,
    trigger_explorer: &mut bool,
) -> ExecResult {
    let Some((name, _args)) = parse_command(input) else {
        return ExecResult::NotACommand;
    };

    match name {
        "help" => {
            let mut help_text = String::from("Available commands:\n");
            for cmd in COMMANDS {
                help_text.push_str(&format!("  /{:<12} {}\n", cmd.name, cmd.description));
            }
            help_text.push_str("\nKeybindings:\n");
            help_text.push_str("  Ctrl+R       Toggle explorer panel\n");
            help_text.push_str("  Ctrl+C       Cancel / clear / quit\n");
            help_text.push_str("  Esc          Clear input\n");
            state.messages.push(ChatMessage {
                role: ChatRole::System,
                content: help_text,
            });
            ExecResult::Handled
        }

        "clear" => {
            state.messages.clear();
            state.messages.push(ChatMessage {
                role: ChatRole::System,
                content: "Chat cleared.".into(),
            });
            ExecResult::Handled
        }

        "quit" => {
            state.should_quit = true;
            ExecResult::Handled
        }

        "explore" => {
            *trigger_explorer = true;
            ExecResult::Handled
        }

        _ => ExecResult::NotACommand,
    }
}
