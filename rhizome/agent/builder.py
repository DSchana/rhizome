"""Agent graph builder — provider-agnostic wrapper around create_agent/init_chat_model."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from rhizome.agent.config import get_api_key
from rhizome.agent.context import AgentContext
from rhizome.agent.middleware import (
    AnthropicPenultimateCacheMiddleware,
    DisableParallelToolCallsMiddleware,
    LogToolCallsMiddleware,
)
from rhizome.logs import get_logger

_logger = get_logger("agent")


def build_agent(
    tools: list,
    provider: str,
    model_name: str,
    response_format: type | None = None,
    **agent_kwargs,
):
    """Build the model + compiled graph.

    This exists primarily to encapsulate provider-specific setup (API keys,
    middleware selection, model defaults) so that callers can construct agents
    without caring which provider is in use.

    Returns a ``(model, agent)`` tuple where *model* is the underlying
    ``BaseChatModel`` and *agent* is the compiled LangGraph state graph.
    """
    _logger.info("Building agent (provider=%s, model=%s)", provider, model_name)

    if provider == "anthropic":
        temperature = agent_kwargs.get("temperature", 0.3)
        model = init_chat_model(
            model_name,
            api_key=get_api_key(),
            temperature=temperature,
        )

        middleware = []

        middleware.append(LogToolCallsMiddleware())

        if not agent_kwargs.get("parallel_tool_calling", True):
            middleware.append(DisableParallelToolCallsMiddleware())

        if agent_kwargs.get("prompt_cache", True):
            ttl = agent_kwargs.get("prompt_cache_ttl", "5m")
            middleware.append(AnthropicPenultimateCacheMiddleware(ttl=ttl))

        # Anthropic server-side tools (executed by the API, not locally).
        # These are passed as dicts — create_agent routes them to bind_tools
        # but not to the ToolNode.
        all_tools: list = list(tools)
        if agent_kwargs.get("web_tools", False):
            all_tools.append({"name": "web_search", "type": "web_search_20260209", "max_uses": 5})
            all_tools.append({"name": "web_fetch", "type": "web_fetch_20260209", "max_uses": 5})
            _logger.info("Web tools enabled (web_search, web_fetch)")

        agent = create_agent(
            model=model,
            tools=all_tools,
            context_schema=AgentContext,
            middleware=middleware,
            response_format=response_format,
            checkpointer=InMemorySaver(),
        )
        return model, agent
    else:
        raise ValueError(f"Unsupported provider: {provider}")
