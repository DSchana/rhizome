# rhizome/agent/middleware/

LangChain agent middleware components for modifying model requests and responses.

## Modules

- **penultimate_cache.py** — `AnthropicPenultimateCacheMiddleware`, places a `cache_control` breakpoint on the penultimate message so that Anthropic's API treats everything before it as a stable, cacheable prefix. Configurable via `ttl` or a custom `cache_control` dict.
- **log_tool_calls.py** — `LogToolCallsMiddleware`, logs every tool invocation at DEBUG level with full arguments via the `wrap_tool_call`/`awrap_tool_call` hooks. Always enabled.
- **disable_parallel_tools.py** — `DisableParallelToolCallsMiddleware`, injects `parallel_tool_calls=False` into `model_settings` on every request. Each tool now has its own session so this is no longer strictly needed for DB safety, but remains as a user-configurable option.
