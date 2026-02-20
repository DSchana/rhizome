"""Build the agent graph (once per app lifetime)."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from curriculum_app.agent.config import get_api_key, get_model_name
from curriculum_app.agent.context import AgentContext
from curriculum_app.agent.tools import get_all_tools


def build_agent():
    """Build and return a compiled agent graph.

    The agent is stateless — per-call context (DB session, system prompt)
    is supplied at invocation time via ``invoke_agent``.
    """
    model = init_chat_model(
        get_model_name(),
        api_key=get_api_key(),
        temperature=0.3,
    )
    return create_agent(
        model=model,
        tools=get_all_tools(),
        context_schema=AgentContext,
    )
