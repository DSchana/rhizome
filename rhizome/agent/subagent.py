"""Subagent: lightweight agent instances that run in isolated context windows."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from rhizome.agent.builder import build_agent
from rhizome.agent.tools import build_tools
from rhizome.logs import get_logger
from rhizome.utils.async_map import AsyncMap

_logger = get_logger("agent.subagent")


@dataclass
class Subagent:
    """A lightweight agent with its own conversation history.

    Unlike ``AgentSession``, a ``Subagent`` does not track token usage,
    manage TUI callbacks, or subscribe to options changes.  It simply
    wraps a compiled LangGraph agent and maintains a message history
    that is fully isolated from the parent session.

    Parameters
    ----------
    model:
        The underlying chat model (kept for utility access).
    agent:
        The compiled LangGraph state graph with tools bound.
    system_prompt:
        Injected as the first ``SystemMessage`` in every conversation.
    stateful:
        If ``True``, conversation history persists across ``ainvoke``
        calls sharing the same ``conversation_id``.  If ``False``,
        each call starts fresh.
    config:
        Optional ``RunnableConfig`` passed to ``agent.ainvoke()``.
    """

    model: Any  # BaseChatModel
    agent: CompiledStateGraph
    system_prompt: str
    stateful: bool = True
    config: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self._history: list[BaseMessage] = [SystemMessage(content=self.system_prompt)]
        self._conversation_id: str | None = None

    @property
    def history(self) -> list[BaseMessage]:
        return self._history

    @property
    def conversation_id(self) -> str | None:
        return self._conversation_id

    def preinvoke_hook(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Override to transform messages before invocation."""
        return messages

    def postinvoke_hook(self, response: AIMessage) -> AIMessage:
        """Override to transform the response after invocation."""
        return response

    async def ainvoke(
        self,
        input: str,
        conversation_id: str | None = None,
    ) -> tuple[str | None, AIMessage]:
        """Invoke the subagent with a human message.

        Returns a ``(conversation_id, ai_message)`` tuple.  The caller
        should pass the returned ``conversation_id`` back on subsequent
        calls to continue the same conversation.
        """
        if (
            conversation_id is None
            or conversation_id != self._conversation_id
            or not self.stateful
        ):
            self._reset_conversation(conversation_id)

        messages = self._history + [HumanMessage(content=input)]
        if self.stateful:
            self._history = messages

        messages = self.preinvoke_hook(messages)

        _logger.debug("Invoking subagent with messages:\n\n%s", "\n\n".join(m.content for m in messages))
        response = await self.agent.ainvoke({"messages": messages}, config=self.config)

        ai_message = response["messages"][-1]
        ai_message = self.postinvoke_hook(ai_message)

        if self.stateful:
            self._history.append(ai_message)

        return self._conversation_id, ai_message

    def _reset_conversation(self, conversation_id: str | None = None) -> None:
        self._history = [SystemMessage(content=self.system_prompt)]
        if not self.stateful:
            self._conversation_id = None
            return
        self._conversation_id = conversation_id or str(uuid.uuid4())


# Type alias — any callable that accepts **kwargs (dataclass, Pydantic model, etc.)
ResponseSchema = type


@dataclass
class StructuredSubagent(Subagent):
    """A subagent that parses structured output from the agent's response.

    The agent is expected to return JSON in its final message content.
    ``postinvoke_hook`` parses this JSON and instantiates ``response_schema``
    with the parsed data, storing the result in the ``response`` property.

    Parameters
    ----------
    response_schema:
        A callable (dataclass, Pydantic model, etc.) that accepts ``**kwargs``
        from the parsed JSON.  Required — raises ``ValueError`` if ``None``.
    """

    response_schema: ResponseSchema | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.response_schema is None:
            raise ValueError("StructuredSubagent requires a response_schema")
        self._structured_response: Any = None

    @property
    def structured_response(self) -> Any:
        """The most recent parsed structured response, or ``None`` if parsing failed."""
        return self._structured_response

    def postinvoke_hook(self, response: AIMessage) -> AIMessage:
        if self.response_schema is not None:
            try:
                # Remark: As of writing (2026-03-04) the langchain documentation says we're supposed to be able to
                # retrieve the structured output from a "structured_response" key [1], however I haven't been able to
                # replicate this. Instead, it seems like the structured response, even with ProviderStrategy, is still
                # returned as just a string in the content field, making it potentially flimsy to decode.
                #
                # [1] - https://docs.langchain.com/oss/python/langchain/structured-output
                #
                # For now, just make sure to include a strict message about the return format in the system prompt.

                # Some more failsafes for different return formats, thanks LangChain...
                content = response.content
                if isinstance(content, list):
                    content = content[-1]
                
                if isinstance(content, dict):
                    if content.get("type") == "text":
                        parsed = json.loads(content["text"])
                    else:
                        parsed = content
                elif isinstance(content, str):
                    parsed = json.loads(content)
                else:
                    raise ValueError(f"Unexpected response content type: {type(content)}")
                self._structured_response = self.response_schema(**parsed)
            except Exception as e:
                _logger.warning("Failed to parse structured response: %s", e)
                _logger.warning(
                    "Full response:\n\n" +
                    response.model_dump_json(indent=2)
                )
                self._structured_response = None
        return response


def build_subagent_tools(
    session_factory,
    chat_pane=None,
    subagents: AsyncMap[str, Subagent] | None = None,
) -> list:
    """Build generic spawn/invoke tools for dynamic subagent management.

    These tools allow the parent agent to create and converse with
    subagents at runtime.  For most use cases, prefer specialized
    subagent classes (e.g. ``CommitSubagent``) that expose
    domain-specific tools instead.

    Parameters
    ----------
    session_factory:
        Async session factory for DB access (passed through to
        ``build_tools``).
    chat_pane:
        Optional TUI chat pane (passed through to ``build_tools``).
    subagents:
        Shared ``AsyncMap`` registry of live subagents.  If ``None``,
        a new one is created.
    """
    from langchain.tools import tool

    if subagents is None:
        subagents = AsyncMap()

    @tool("spawn_subagent", description=(
        "Create a new subagent with its own isolated context. "
        "Returns the subagent name for use with invoke_subagent."
    ))
    async def spawn_subagent(
        name: str,
        system_prompt: str,
        tools: list[str] | None = None,
        stateful: bool = True,
    ) -> str:
        existing = await subagents.get(name)
        if existing is not None:
            return json.dumps({"error": f"Subagent '{name}' already exists."})

        subagent_tools = build_tools(
            session_factory,
            chat_pane=chat_pane,
            included=tools,
        )

        model, agent, _middleware = build_agent(
            subagent_tools,
            provider="anthropic",
            model_name=None,
        )

        subagent = Subagent(
            model=model,
            agent=agent,
            system_prompt=system_prompt,
            stateful=stateful,
        )
        await subagents.set(name, subagent)

        return json.dumps({"created": name, "stateful": stateful})

    @tool("invoke_subagent", description=(
        "Send a message to an existing subagent and get its response. "
        "Pass conversation_id from a previous response to continue "
        "the same conversation."
    ))
    async def invoke_subagent(
        subagent_id: str,
        input: str,
        conversation_id: str | None = None,
        output_format: str = "default",
    ) -> str:
        subagent = await subagents.get(subagent_id)
        if subagent is None:
            return json.dumps({"error": f"Subagent '{subagent_id}' not found."})

        conv_id, response = await subagent.ainvoke(input, conversation_id)

        output: dict[str, Any] = {}
        if conv_id is not None:
            output["conversation_id"] = conv_id

        if output_format == "default":
            output["response"] = response.content
        elif output_format == "raw":
            output["raw_response"] = response.model_dump()
        else:
            output["response"] = response.content

        return json.dumps(output, indent=2, default=str)

    return [spawn_subagent, invoke_subagent]
