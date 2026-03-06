# rhizome/agent/middleware/

LangChain agent middleware components for modifying model requests and responses.

## Modules

- **inject_user_settings.py** — `InjectUserSettingsMiddleware[ContextT]`, a generic middleware that injects user settings into the last human message. Settings can be provided either by passing `settings_attribute` (a context attribute name) or by subclassing and implementing `get_settings(context)`. Subclasses can also override `wrap_message(msg, context)` to customise presentation. Provides an optional `system_prompt()` classmethod explaining the settings format to the agent (opt-in via `include_system_prompt=True`).
- **penultimate_cache.py** — `AnthropicPenultimateCacheMiddleware`, places a `cache_control` breakpoint on the penultimate message so that Anthropic's API treats everything before it as a stable, cacheable prefix. Configurable via `ttl` or a custom `cache_control` dict.
- **log_tool_calls.py** — `LogToolCallsMiddleware`, logs every tool invocation at DEBUG level with full arguments via the `wrap_tool_call`/`awrap_tool_call` hooks. Always enabled.
- **disable_parallel_tools.py** — `DisableParallelToolCallsMiddleware`, injects `parallel_tool_calls=False` into `model_settings` on every request. Each tool now has its own session so this is no longer strictly needed for DB safety, but remains as a user-configurable option.
