# Open Questions

- **Conversation scoping for commits**: Should `/commit` always operate on the entire conversation, or should the user be able to select a range of messages?
- **Multi-topic commits**: What if a conversation spans multiple topics? Allow per-entry topic override during commit?
- **Undo**: How granular should undo be? Single entry? Entire commit batch?
- **Chat history persistence**: Should conversations be saved to the database independently of committed knowledge entries? This would allow re-committing from past sessions.
