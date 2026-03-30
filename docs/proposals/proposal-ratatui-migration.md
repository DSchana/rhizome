# Proposal: Ratatui Migration

**Status:** Under consideration
**Date:** 2026-03-26
**Motivation:** Textual exhibits redraw issues and lag with many widgets that are outside our control.

## Background

Ratatui is an immediate-mode TUI rendering library for Rust (~19k GitHub stars, used by Netflix/OpenAI/AWS). Unlike Textual's retained-mode DOM approach, ratatui redraws every frame from scratch with no persistent widget tree, relying on double-buffered diffing to minimize terminal writes.

## Ratatui vs Textual

| Dimension | Textual | Ratatui |
|---|---|---|
| **Rendering model** | Retained-mode DOM (like a web browser) | Immediate-mode (like a game engine) |
| **State ownership** | Framework owns widget state + app state | App owns all state; ratatui owns none |
| **Styling** | CSS selectors, inheritance, cascade (TCSS) | Inline style structs, no cascade |
| **Events** | Message bus with bubbling/propagation | Manual polling from terminal backend (crossterm) |
| **Structure** | Framework provides lifecycle, screens, reactivity | You architect everything yourself |
| **Widgets** | 30+ built-in (Button, Input, Tree, Markdown, DataTable, etc.) | 14 built-in (Block, Paragraph, List, Table, Chart, etc.) |
| **Layout** | CSS-like (margin, padding, dock, grid, layers) | Constraint-based Cassowary solver (Length, %, Min, Max, Fill) |
| **Async** | Built on asyncio natively | Not built-in; opt into tokio |
| **Testing** | Built-in pilot framework | No built-in test framework |
| **Web support** | `textual serve` for browser deployment | Terminal only |
| **Language** | Python | Rust |

## What We'd Gain

- **Dramatically better performance** — native Rust, no interpreter, no DOM overhead, no GC, zero-allocation rendering. The redraw issues and widget lag we're hitting would not exist.
- **Simpler mental model** — render is a pure function of state. No hidden reactive cascades, no CSS specificity surprises, no framework magic.
- **Single binary distribution** — no Python runtime needed for end users.
- **Full control** — we own the event loop, render timing, and architecture with nothing imposed.

## What We'd Lose

- **Rich widget set** — no built-in TextInput, Button, Checkbox, Tree, Markdown renderer, DataTable. Must build or find crates.
- **CSS styling** — every visual change requires recompiling Rust code.
- **Framework structure** — no screens, no message bus, no reactive properties, no `compose()` pattern. All must be designed from scratch.
- **Development speed** — Rust compile times vs Python's instant iteration.
- **Web deployment** — Textual can serve apps in a browser; ratatui is terminal-only.
- **Testing** — no equivalent to Textual's pilot testing framework.

## Migration Scope

Current Textual integration: **~10,150 lines across 40 files** with 28 custom widgets.

### Largest components
- ChatPane (1,391 LOC) — chat history, message input, command dispatch, agent session management
- FlashcardReview (948 LOC) — spaced repetition UI with keyboard navigation
- CommitProposal (796 LOC) — DB commit preview and approval
- FlashcardProposal (682 LOC) — flashcard creation interface
- ExplorerViewer (610 LOC) — multi-pane explorer for topics/entries/flashcards
- TopicTree (437 LOC), AgentMessageHarness (355 LOC), OptionsEditor (347 LOC), EntryList (327 LOC), etc.

### Reusable code (~500-700 LOC, no Textual dependency)
- `tui/types.py` — enums and dataclasses (Mode, Role, ChatMessageData)
- `tui/commands.py` — command parser and registry (uses Click)
- `tui/options.py` — options pub/sub system (partially reusable)
- `tui/colors.py`, `tui/utils.py`, `tui/commit_state.py`

### Cross-layer Textual coupling
- `agent/tools/app.py` imports `Mode` and `HintHigherVerbosity` message
- `agent/subagents/commit.py` imports `CommitApproved` message
- These are data-focused and could be decoupled.

### Key framework features to reimplement
1. Message-driven architecture (Textual's `Message` / `post_message()`)
2. Reactive properties (`@reactive` decorator)
3. Widget composition (`compose()` / `ComposeResult`)
4. Keyboard binding system (`BINDINGS` + action methods)
5. Screen stack management (`push_screen()` / `pop_screen()`)
6. Worker threads (`textual.worker.Worker` for async tasks)

## Language Bridge Problem

The DB layer (async SQLAlchemy/aiosqlite) and agent layer are Python. A full ratatui migration means either:
1. **Rewrite everything in Rust** — largest scope, cleanest result
2. **Rust TUI ↔ Python backend over IPC** — JSON-RPC, gRPC, or Unix sockets. Adds complexity but preserves existing Python code.

## Alternatives Worth Exploring

- **Profile Textual bottlenecks first** — widget virtualization, reducing compose depth, batching updates might solve the issues without a rewrite
- **cursive** (Rust) — retained-mode TUI, closer to Textual's model but in Rust
- **tui-realm** (Rust) — component framework built on ratatui, provides some of the structure ratatui lacks
- **Hybrid approach** — Rust ratatui binary for TUI, Python backend over IPC
