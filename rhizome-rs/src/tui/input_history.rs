//! Command history buffer — up/down arrow recall for chat input.
//!
//! Mirrors Python's ChatInput._history behavior: a ring buffer of
//! previous inputs with a draft stash for the current unsent text.

/// Stores previous input submissions and allows up/down navigation.
pub struct InputHistory {
    entries: Vec<String>,
    /// Current position in history. None = at the live draft.
    position: Option<usize>,
    /// Stashed draft text (saved when user starts navigating history).
    draft: String,
    max_entries: usize,
}

impl InputHistory {
    pub fn new(max_entries: usize) -> Self {
        Self {
            entries: Vec::new(),
            position: None,
            draft: String::new(),
            max_entries,
        }
    }

    /// Record a submitted input line.
    pub fn push(&mut self, text: String) {
        // Don't push duplicates of the most recent entry
        if self.entries.last().map(|s| s.as_str()) == Some(&text) {
            self.position = None;
            return;
        }
        self.entries.push(text);
        if self.entries.len() > self.max_entries {
            self.entries.remove(0);
        }
        self.position = None;
    }

    /// Navigate to the previous (older) entry. Returns the text to show.
    /// `current_text` is the text currently in the input (stashed on first call).
    pub fn prev(&mut self, current_text: &str) -> Option<&str> {
        if self.entries.is_empty() {
            return None;
        }
        match self.position {
            None => {
                // First press: stash current text, go to most recent
                self.draft = current_text.to_string();
                let idx = self.entries.len() - 1;
                self.position = Some(idx);
                Some(&self.entries[idx])
            }
            Some(0) => {
                // Already at oldest entry
                Some(&self.entries[0])
            }
            Some(idx) => {
                let new_idx = idx - 1;
                self.position = Some(new_idx);
                Some(&self.entries[new_idx])
            }
        }
    }

    /// Navigate to the next (newer) entry. Returns the text to show.
    pub fn next(&mut self) -> Option<&str> {
        match self.position {
            None => None, // already at live draft
            Some(idx) => {
                if idx + 1 >= self.entries.len() {
                    // Past the newest entry — restore draft
                    self.position = None;
                    Some(&self.draft)
                } else {
                    let new_idx = idx + 1;
                    self.position = Some(new_idx);
                    Some(&self.entries[new_idx])
                }
            }
        }
    }

    /// Reset navigation position (called when user types anything).
    pub fn reset_position(&mut self) {
        self.position = None;
    }
}
