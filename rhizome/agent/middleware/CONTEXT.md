# rhizome/agent/middleware/

LangChain agent middleware components for modifying model requests and responses.

## Modules

- **cache_aware_settings.py** — `AnthropicCacheAwareSettingsMiddleware[ContextT]`, a generic middleware that injects user settings into the last human message while preserving Anthropic's prefix-based prompt cache. Settings can be provided either by passing `settings_attribute` (a context attribute name) or by subclassing and implementing `get_settings(context)`. Subclasses can also override `wrap_message(msg, context)` to customise presentation. Provides an optional `system_prompt()` classmethod explaining the settings format to the agent (opt-in via `include_system_prompt=True`).
