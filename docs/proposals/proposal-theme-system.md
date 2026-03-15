# Theme System Proposal

## Current State: Color Inventory

All colors live exclusively in the TUI layer (`rhizome/tui/`). Some are centralized in `colors.py`, but many are hardcoded across widget files.

### Centralized Constants (`rhizome/tui/colors.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `USER_BG` | `rgb(22, 22, 22)` | User message background |
| `USER_PREFIX` | `rgb(100, 160, 230)` | User role prefix |
| `AGENT_PREFIX` | `rgb(200, 100, 200)` | Agent role prefix |
| `SYSTEM_PREFIX` | `rgb(140, 140, 140)` | System role prefix |
| `TOOLCALL_TITLE` | `rgb(220, 160, 80)` | Tool call header |
| `SYSTEM_ERROR` | `rgb(220, 80, 80)` | Error messages |
| `LEARN_AGENT_BORDER` | `rgb(60, 80, 160)` | Learn mode border |
| `LEARN_SYSTEM_TEXT` | `rgb(110, 140, 240)` | Learn mode text |
| `REVIEW_AGENT_BORDER` | `rgb(120, 60, 160)` | Review mode border |
| `REVIEW_SYSTEM_TEXT` | `rgb(170, 90, 220)` | Review mode text |
| `COMMIT_SELECTABLE` | `rgb(140, 120, 50)` | Commit selectable border |
| `COMMIT_CURSOR` | `rgb(220, 190, 60)` | Commit cursor border |
| `COMMIT_SELECTED` | `rgb(60, 160, 80)` | Commit selected border |
| `COMMIT_SELECTED_CURSOR` | `rgb(80, 200, 100)` | Commit selected+cursor |

### Hardcoded in Widget Files

**Backgrounds:**
- `rgb(12, 12, 12)` — chat pane (`chat_pane.py`), logging pane (`logging_pane.py`)
- `rgb(16, 16, 16)` — options editor (`options_editor.py`)
- `rgb(45, 45, 45)` — ping animation (`message.py`)

**Borders/Separators:**
- `rgb(50, 50, 50)` — rule separators (`options_editor.py`)
- `rgb(60, 60, 60)` — borders, scrollbars (`chat_pane.py`, `command_palette.py`, `logging_pane.py`)
- `rgb(80, 80, 80)` — scrollbar hover, tool argument dim, done button border, hint text (`chat_pane.py`, `tool_call_list.py`, `commit_proposal.py`, `options_editor.py`)
- `rgb(86, 126, 160)` — command palette highlight, topic tree border, options editor border (`command_palette.py`, `topic_tree.py`, `options_editor.py`)
- `rgb(80, 120, 90)` — welcome banner border (`welcome.py`)

**Text colors (grays):**
- `rgb(90, 90, 90)` — model name text (`status_bar.py`)
- `rgb(100, 100, 100)` — secondary/hint text (~6 files: `status_bar.py`, `tool_call_list.py`, `interrupt_choices.py`, `interrupt_warning.py`, `commit_proposal.py`, `topic_selector.py`)
- `rgb(120, 120, 120)` — verbosity terse, done button hover border (`status_bar.py`, `options_editor.py`)
- `rgb(140, 140, 140)` — status bar labels (`status_bar.py`)
- `rgb(204, 204, 204)` — message content text (`message.py`)

**Accent colors:**
- `rgb(90, 210, 190)` — verbosity verbose indicator (`status_bar.py`)
- `rgb(220, 160, 50)` — warning icon/message (`interrupt_warning.py`)
- `rgb(220, 160, 80)` — tool overhead text (`status_bar.py`)
- `rgb(255, 80, 80)` — commit proposal red (`commit_proposal.py`)
- `rgb(255, 80, 255)` — verbosity auto indicator (`status_bar.py`)
- `rgb(255, 255, 255)` / `#ffffff` — white (`status_bar.py`, `command_palette.py`)

### Textual CSS Variables Already in Use
`$surface`, `$surface-lighten-2`, `$surface-darken-1`, `$text`, `$text-muted`, `$accent`, `$error`

### Rich Markup Colors (`log_handler.py`, interrupt widgets)
`dim`, `bold blue`, `bold yellow`, `bold red`, `bold red reverse`, `bold white`

---

## How Themes Work in Mature Editors

### The Universal Pattern: Two-Layer Indirection

Every major editor uses the same core architecture:

1. **Palette layer** — a small set of raw color values (hex/rgb). This is the *only* thing that changes between themes.
2. **Semantic role layer** — maps UI purposes to palette entries. Widgets reference roles, never raw colors.

### VS Code
- Theme = JSON file with `type` (dark/light), `colors` (700+ semantic keys like `editor.background`, `statusBar.foreground`), and `tokenColors` (syntax highlighting).
- Naming: `component.property` dot-notation — `sideBar.background`, `button.hoverBackground`.
- User overrides via `workbench.colorCustomizations` in settings, can even be scoped per-theme.

### Sublime Text
- Modern `.sublime-color-scheme` has three sections: `variables` (raw palette), `globals` (editor-wide semantic roles), `rules` (syntax scopes).
- The `variables` → `var()` reference pattern cleanly separates palette from usage.
- User overrides by placing a same-named file in `Packages/User/` (merged automatically).

### Atom (Historical)
- Two theme types: **UI themes** (chrome) and **syntax themes** (editor content), both in Less.
- Contract via required Less variables: `@syntax-background-color`, `@text-color-subtle`, `@button-background-color`, etc.
- Raw palette in `colors.less`, semantic mapping in `*-variables.less`, application in `base.less`.

### Key Principles

| Principle | Details |
|-----------|---------|
| **Semantic indirection** | Widgets never reference hex values directly — they reference roles like `surface`, `text.muted`, `border.focus` |
| **Light/dark are separate definitions** | No editor auto-derives one from the other; each variant is authored independently |
| **Layered overrides** | Base theme → user overrides, merged without forking |
| **Role naming avoids color words** | `accent` not `blue`, `surface` not `dark-gray` |
| **Flat unless complex** | `surface`, `text-muted`, `border-focus` — only use `component.role` when needed |

---

## Recommended Approach for Rhizome

Textual already provides a `Theme` object with ~11 base colors and auto-generated shade variants (`$primary-lighten-1`, etc.) exposed as CSS variables. We should build on top of that.

### Architecture

1. **Define a palette** — 10-15 named raw colors in one place (Python dict or dataclass).
2. **Define semantic roles** — map purposes to palette entries:
   - `surface`, `surface-alt`, `panel-bg`
   - `text`, `text-muted`, `text-accent`
   - `border`, `border-focus`
   - `accent`, `error`, `warning`
   - `mode-learn`, `mode-review`
   - `commit-selectable`, `commit-cursor`, `commit-selected`, `commit-selected-cursor`
   - `user-prefix`, `agent-prefix`, `system-prefix`
   - `toolcall-title`, `system-error`
3. **Widgets reference only roles** — no `rgb(...)` scattered across files.
4. **Each theme = a different palette → role mapping** — swap one dict, everything updates.
5. **User overrides** — load base theme, overlay a user config file (TOML) on top.

### Migration Path

The current codebase has ~31 unique RGB values hardcoded across ~15 files, plus 7 Textual CSS variables already used semantically. The migration would:

1. Audit every hardcoded color (see inventory above).
2. Assign each to a semantic role name.
3. Centralize all role definitions in one module (expanding `colors.py` or replacing it).
4. Update all widget files to reference roles instead of raw values.
5. Wire the role definitions into Textual's theme/CSS variable system.
6. Define at least one complete theme (the current dark theme) as the default.
