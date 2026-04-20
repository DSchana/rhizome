//! Status bar — 3-line bar at the bottom showing mode, topic, tokens, and verbosity.

use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Style},
    text::{Line, Span},
    widgets::Widget,
};

/// Active operating mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Mode {
    #[default]
    Idle,
    Learn,
    Review,
    Thinking,
}

/// Verbosity level.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Verbosity {
    Terse,
    Standard,
    Verbose,
    #[default]
    Auto,
}

/// All data rendered in the status bar.
pub struct StatusInfo {
    pub mode: Mode,
    pub topic_path: Vec<String>,
    pub model_name: String,
    pub total_tokens: u64,
    pub system_tokens: Option<u64>,
    pub tool_tokens: Option<u64>,
    pub context_usage_pct: Option<f64>,
    pub cache_read_tokens: Option<u64>,
    pub cache_creation_tokens: Option<u64>,
    pub verbosity: Verbosity,
}

impl Default for StatusInfo {
    fn default() -> Self {
        Self {
            mode: Mode::Idle,
            topic_path: Vec::new(),
            model_name: "claude-sonnet-4-20250514".into(),
            total_tokens: 0,
            system_tokens: None,
            tool_tokens: None,
            context_usage_pct: None,
            cache_read_tokens: None,
            cache_creation_tokens: None,
            verbosity: Verbosity::Auto,
        }
    }
}

// ── Color constants ──────────────────────────────────────────────────

const LABEL: Color = Color::Rgb(140, 140, 140);
const DIM_HINT: Color = Color::Rgb(100, 100, 100);
const MODEL_NAME_COLOR: Color = Color::Rgb(90, 90, 90);
const MODE_LEARN: Color = Color::Rgb(110, 140, 240);
const MODE_REVIEW: Color = Color::Rgb(170, 90, 220);
const SYSTEM_TOKENS_COLOR: Color = Color::Rgb(120, 120, 120);
const TOOL_TOKENS_COLOR: Color = Color::Rgb(220, 160, 80);
const VERBOSITY_TERSE: Color = Color::Rgb(120, 120, 120);
const VERBOSITY_VERBOSE: Color = Color::Rgb(90, 210, 190);
const VERBOSITY_AUTO: Color = Color::Rgb(255, 80, 255);
const CACHE_STATS_COLOR: Color = Color::Rgb(90, 90, 90);

// ── Helpers ──────────────────────────────────────────────────────────

/// Format a number with thousands separators: 1234 -> "1,234"
fn fmt_thousands(n: u64) -> String {
    let s = n.to_string();
    let mut result = String::with_capacity(s.len() + s.len() / 3);
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            result.push(',');
        }
        result.push(c);
    }
    result
}

/// Compute the display width of a slice of Spans (character count).
fn spans_width(spans: &[Span<'_>]) -> usize {
    spans.iter().map(|s| s.content.len()).sum()
}

/// Build a single Line by right-aligning `right` spans after `left` spans,
/// filling the gap with spaces up to `total_width`.
fn right_aligned_line<'a>(left: Vec<Span<'a>>, right: Vec<Span<'a>>, total_width: u16) -> Line<'a> {
    let left_w = spans_width(&left);
    let right_w = spans_width(&right);
    let gap = (total_width as usize).saturating_sub(left_w + right_w).max(2);

    let mut spans = left;
    spans.push(Span::raw(" ".repeat(gap)));
    spans.extend(right);
    Line::from(spans)
}

// ── Topic path truncation ────────────────────────────────────────────

const TOPIC_PATH_MAX: usize = 60;

fn render_topic_path(path: &[String]) -> Span<'static> {
    if path.is_empty() {
        return Span::styled("none".to_string(), Style::default().fg(DIM_HINT));
    }
    let sep = " > ";
    let full = path.join(sep);
    if full.len() <= TOPIC_PATH_MAX {
        Span::raw(full)
    } else {
        let mut parts: Vec<&str> = path.iter().map(|s| s.as_str()).collect();
        let prefix = "... > ";
        while parts.len() > 1 {
            parts.remove(0);
            let candidate = format!("{}{}", prefix, parts.join(sep));
            if candidate.len() <= TOPIC_PATH_MAX {
                return Span::raw(candidate);
            }
        }
        Span::raw(format!("{}{}", prefix, parts.join(sep)))
    }
}

// ── Widget ───────────────────────────────────────────────────────────

/// A stateless widget that renders the 3-line status bar.
pub struct StatusBar<'a> {
    pub info: &'a StatusInfo,
}

impl Widget for StatusBar<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let w = area.width;
        let info = self.info;

        // ── Line 1: topic (left), model name (right) ────────────────
        let left1 = vec![
            Span::styled("topic: ", Style::default().fg(LABEL)),
            render_topic_path(&info.topic_path),
        ];
        let right1 = if info.model_name.is_empty() {
            vec![]
        } else {
            vec![Span::styled(
                info.model_name.clone(),
                Style::default().fg(MODEL_NAME_COLOR),
            )]
        };
        let line1 = right_aligned_line(left1, right1, w);

        // ── Line 2: mode (left), token usage (right) ────────────────
        let (mode_str, mode_color) = match info.mode {
            Mode::Idle => ("idle", Color::White),
            Mode::Learn => ("learn", MODE_LEARN),
            Mode::Review => ("review", MODE_REVIEW),
            Mode::Thinking => ("thinking", Color::Yellow),
        };
        let left2 = vec![
            Span::styled("mode: ", Style::default().fg(LABEL)),
            Span::styled(mode_str, Style::default().fg(mode_color)),
            Span::styled("  (shift+tab to cycle)", Style::default().fg(DIM_HINT)),
        ];

        let right2 = if info.total_tokens > 0 {
            let mut spans = vec![Span::raw(format!("tokens: {}", fmt_thousands(info.total_tokens)))];

            let has_breakdown = info.system_tokens.is_some() || info.tool_tokens.is_some();
            if has_breakdown {
                spans.push(Span::styled(" (", Style::default().fg(DIM_HINT)));
                let mut parts_added = 0;
                if let Some(sys) = info.system_tokens {
                    spans.push(Span::styled(
                        format!("system: {}", fmt_thousands(sys)),
                        Style::default().fg(SYSTEM_TOKENS_COLOR),
                    ));
                    parts_added += 1;
                }
                if let Some(tools) = info.tool_tokens {
                    if parts_added > 0 {
                        spans.push(Span::styled(", ", Style::default().fg(DIM_HINT)));
                    }
                    spans.push(Span::styled(
                        format!("tools: {}", fmt_thousands(tools)),
                        Style::default().fg(TOOL_TOKENS_COLOR),
                    ));
                }
                spans.push(Span::styled(")", Style::default().fg(DIM_HINT)));
            }

            if let Some(pct) = info.context_usage_pct {
                spans.push(Span::raw(format!("  context usage: {:.1}%", pct)));
            }

            spans
        } else {
            vec![]
        };
        let line2 = right_aligned_line(left2, right2, w);

        // ── Line 3: verbosity (left), cache stats (right) ───────────
        let (verb_str, verb_color) = match info.verbosity {
            Verbosity::Terse => ("terse", VERBOSITY_TERSE),
            Verbosity::Standard => ("standard", Color::White),
            Verbosity::Verbose => ("verbose", VERBOSITY_VERBOSE),
            Verbosity::Auto => ("auto", VERBOSITY_AUTO),
        };
        let left3 = vec![
            Span::styled("verbosity: ", Style::default().fg(LABEL)),
            Span::styled(verb_str, Style::default().fg(verb_color)),
            Span::styled("  (ctrl+b to cycle)", Style::default().fg(DIM_HINT)),
        ];

        let right3 = match (info.cache_read_tokens, info.cache_creation_tokens) {
            (Some(read), Some(create)) => vec![Span::styled(
                format!("cache read: {}  create: {}", fmt_thousands(read), fmt_thousands(create)),
                Style::default().fg(CACHE_STATS_COLOR),
            )],
            (Some(read), None) => vec![Span::styled(
                format!("cache read: {}", fmt_thousands(read)),
                Style::default().fg(CACHE_STATS_COLOR),
            )],
            (None, Some(create)) => vec![Span::styled(
                format!("cache create: {}", fmt_thousands(create)),
                Style::default().fg(CACHE_STATS_COLOR),
            )],
            (None, None) => vec![],
        };
        let line3 = right_aligned_line(left3, right3, w);

        // ── Write to buffer ──────────────────────────────────────────
        if area.height >= 1 {
            buf.set_line(area.x, area.y, &line1, w);
        }
        if area.height >= 2 {
            buf.set_line(area.x, area.y + 1, &line2, w);
        }
        if area.height >= 3 {
            buf.set_line(area.x, area.y + 2, &line3, w);
        }
    }
}
