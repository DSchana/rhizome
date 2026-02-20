# TUI Overarching Plan

Draft design for the rhizome terminal user interface.

## Overview

The TUI is a chat-based interface (Textual) modeled after Claude Code. The user launches the app and is greeted with a welcome screen and an input box. From here they can type freely or use slash-commands to enter specific modes.

### Top-level slash-commands

| Command    | Purpose                                           |
|------------|---------------------------------------------------|
| `/learn`   | Enter learning mode: set context, chat, commit knowledge |
| `/review`  | Enter review mode: quizzes and practice           |
| `/options` | Open settings and configuration                   |

---

## Mapping to Existing Backend

The current tool functions already support the commit workflow:

| Workflow step              | Tool function(s)                                       |
|----------------------------|--------------------------------------------------------|
| Select/create curriculum   | `list_curricula`, `create_curriculum`                  |
| Select/create topic        | `list_topics`, `create_topic`                          |
| Commit entry               | `create_entry(topic_id, title, content, entry_type, additional_notes)` |
| Tag entry                  | `tag_entry(entry_id, tag_name)` (creates tag if needed)|
| Browse entries             | `list_entries(topic_id)`, `search_entries(query)`      |
| Review — fetch entries     | `list_entries`, `search_entries`, `get_entries_by_tag`  |
| Relate entries             | `add_relation(source_id, target_id, rel_type)`         |
