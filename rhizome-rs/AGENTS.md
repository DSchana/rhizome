# AGENTS.md — rhizome-rs

## Commands

```bash
cargo build     # build the TUI binary
cargo run       # run the TUI (requires ~/.config/rhizome/credentials.json)
cargo check     # fast type-check without full codegen
```

No test framework exists. Verify manually with `cargo run`.

## Prerequisites

- **Rust 1.85+** required — `edition = "2024"` in Cargo.toml.
- **Anthropic API key** in `~/.config/rhizome/credentials.json`:
  ```json
  { "anthropic_api_key": "sk-ant-..." }
  ```
  Optional: `"db_path"` field overrides the default `rhizome.db` in cwd.

## Architecture

Single binary crate. Four modules under `src/`:

- **`db/`** — SQLx + raw SQL against SQLite. `init_db()` creates the pool (FK enforcement via `PRAGMA foreign_keys=ON`) and runs migrations via `sqlx::migrate!("./migrations")`.
- **`agent/`** — Custom Anthropic Messages API client (no SDK). Streams SSE over reqwest, parses events manually. Tool dispatch loop re-calls the API after tool results.
- **`tui/`** — Ratatui app. Agent runs on its own tokio task; communicates with the main loop via `mpsc` channels (`AgentEvent` enum).
- **`config.rs`** — Reads `~/.config/rhizome/credentials.json` for API key and db path.

## Migrations

Raw `.sql` files in `migrations/`, loaded by `sqlx::migrate!` at runtime (not sqlx-cli). Naming: `YYYYMMDDNN_description.sql`. The macro validates filenames at compile time.

## Key Gotchas

- **Tag normalization**: tag names are lowercased on create/lookup. Don't assume case-sensitive matching.
- **Cycle detection**: `relations::add_relation` runs a recursive CTE before insert. Returns `RelationError::CycleDetected`.
- **Partial updates**: `update_topic` / `update_entry` fetch the existing row first and merge `None` args with existing values.
- **Delete semantics**: deleting a topic cascades to entries (SQL `ON DELETE CASCADE`), but **fails** if it has child topics (FK constraint prevents orphans).
- **SQLite timestamps**: stored as `INTEGER` via `unixepoch()`, but Rust models use `chrono::DateTime<Utc>`. SQLx handles conversion.
- **Cargo.lock is gitignored** — this is a binary crate, so `Cargo.lock` should ideally be committed. The `.gitignore` entry is likely a mistake.
- **`*.db` files are gitignored** — test databases won't appear in `git status`.
- **Agent SSE parsing**: hand-rolled in `client.rs` — splits on `\n`, accumulates `data:` lines. Not using an SSE library.
