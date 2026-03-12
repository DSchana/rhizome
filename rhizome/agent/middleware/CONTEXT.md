# rhizome/agent/middleware/

LangChain agent middleware components for modifying model requests and responses.

## Modules

- **agent_mode.py** — `AgentModeMiddleware`, reads the active `AgentMode` from the session on every model call. Uses two hooks: `abefore_model` idempotently replaces the `SystemMessage` in graph state (by well-known ID `SYSTEM_PROMPT_MESSAGE_ID`) when the mode's prompt differs from the current one, and `awrap_model_call` statelessly filters `request.tools` to the mode's allowlist. The initial system message is seeded in `AgentSession.__init__` with the well-known ID; the middleware replaces it in-place via the `add_messages` reducer when the mode changes. No manual system message queuing is needed on mode change — the middleware handles it.
- **penultimate_cache.py** — `AnthropicPenultimateCacheMiddleware`, places a `cache_control` breakpoint on the penultimate message so that Anthropic's API treats everything before it as a stable, cacheable prefix. Configurable via `ttl` or a custom `cache_control` dict.
- **log_tool_calls.py** — `LogToolCallsMiddleware`, logs every tool invocation at DEBUG level with full arguments via the `wrap_tool_call`/`awrap_tool_call` hooks. Always enabled.
- **disable_parallel_tools.py** — `DisableParallelToolCallsMiddleware`, injects `parallel_tool_calls=False` into `model_settings` on every request. Each tool now has its own session so this is no longer strictly needed for DB safety, but remains as a user-configurable option.
