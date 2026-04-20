//! Thinking indicator — braille character animation.
//!
//! Mirrors Python's ThinkingIndicator: cycles through braille frames
//! at ~100ms intervals (driven by the Tick event).

const FRAMES: &[char] = &['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

/// Get the spinner text for a given frame counter.
pub fn spinner_text(frame: u8) -> String {
    let ch = FRAMES[(frame as usize) % FRAMES.len()];
    format!("{} thinking...", ch)
}

/// Advance the frame counter (wrapping).
pub fn advance_frame(frame: u8) -> u8 {
    frame.wrapping_add(1)
}
