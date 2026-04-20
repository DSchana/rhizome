//! Slash command registry and dispatch.
//!
//! Commands are defined statically and dispatched by name.
//! Each command returns an `Action` that the main loop handles.

/// Definition of a slash command (for display in the palette).
#[derive(Debug, Clone)]
pub struct CommandDef {
    pub name: &'static str,
    pub description: &'static str,
}

/// The result of executing a command — tells the main loop what to do.
#[derive(Debug)]
pub enum CommandAction {
    /// Do nothing (command handled internally or was just info)
    None,
    /// Show a system message in the chat
    Message(String),
    /// Clear the chat history
    Clear,
    /// Quit the application
    Quit,
    /// Create a new tab
    NewTab,
    /// Close the active tab
    CloseTab,
    /// Set session mode
    SetMode(crate::tui::tab::SessionMode),
    /// Toggle the sidebar
    ToggleSidebar,
    /// Toggle the explorer
    ToggleExplorer,
    /// Rename the active tab
    Rename(String),
}

/// All available commands.
pub static COMMANDS: &[CommandDef] = &[
    CommandDef {
        name: "help",
        description: "Show available commands",
    },
    CommandDef {
        name: "quit",
        description: "Exit the application",
    },
    CommandDef {
        name: "clear",
        description: "Clear chat messages",
    },
    CommandDef {
        name: "new",
        description: "Open a new tab",
    },
    CommandDef {
        name: "close",
        description: "Close the current tab",
    },
    CommandDef {
        name: "rename",
        description: "Rename current tab: /rename <name>",
    },
    CommandDef {
        name: "idle",
        description: "Switch to idle mode",
    },
    CommandDef {
        name: "learn",
        description: "Switch to learning mode",
    },
    CommandDef {
        name: "review",
        description: "Switch to review mode",
    },
    CommandDef {
        name: "explore",
        description: "Open the topic/entry explorer",
    },
    CommandDef {
        name: "topics",
        description: "Toggle the topic tree sidebar",
    },
];

/// Parse and execute a slash command. Returns the action to take.
pub fn execute(input: &str) -> CommandAction {
    let input = input.trim();

    // Strip the leading `/`
    let cmd_line = if let Some(rest) = input.strip_prefix('/') {
        rest
    } else {
        return CommandAction::None;
    };

    let mut parts = cmd_line.splitn(2, ' ');
    let cmd_name = parts.next().unwrap_or("").to_lowercase();
    let args = parts.next().unwrap_or("").trim();

    match cmd_name.as_str() {
        "help" => {
            let mut help = String::from("Available commands:\n");
            for cmd in COMMANDS {
                help.push_str(&format!("  /{} — {}\n", cmd.name, cmd.description));
            }
            CommandAction::Message(help)
        }
        "quit" | "q" => CommandAction::Quit,
        "clear" => CommandAction::Clear,
        "new" => CommandAction::NewTab,
        "close" => CommandAction::CloseTab,
        "rename" => {
            if args.is_empty() {
                CommandAction::Message("Usage: /rename <name>".into())
            } else {
                CommandAction::Rename(args.to_string())
            }
        }
        "idle" => CommandAction::SetMode(crate::tui::tab::SessionMode::Idle),
        "learn" => CommandAction::SetMode(crate::tui::tab::SessionMode::Learn),
        "review" => CommandAction::SetMode(crate::tui::tab::SessionMode::Review),
        "explore" => CommandAction::ToggleExplorer,
        "topics" => CommandAction::ToggleSidebar,
        other => CommandAction::Message(format!("Unknown command: /{}", other)),
    }
}
