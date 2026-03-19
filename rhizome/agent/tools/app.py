"""App control tools — mode switching, tab renaming, topic selection, user input."""

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.operations import get_topic
from rhizome.tui.types import Mode


class Question(BaseModel):
    """A single multiple-choice question presented to the user."""

    name: str = Field(description="Short tab label (1-2 words)")
    prompt: str = Field(description="Full question text shown to the user")
    options: list[str] = Field(description="List of option strings to choose from")


def build_app_tools(session_factory, chat_pane=None) -> dict:
    """Build app control tools with session_factory and chat_pane closed over."""

    @tool("set_topic", description=(
        "Set the active topic for this chat session. "
        "Updates the status bar and notifies the user. "
        "Use this when the user begins learning about a specific topic."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def set_topic_tool(topic_id: int) -> str:
        if chat_pane is None:
            return "Chat pane not available."
        async with session_factory() as session:
            topic = await get_topic(session, topic_id)
            if topic is None:
                return f"Topic {topic_id} not found."
            # Walk up parents to build the path
            path: list[str] = [topic.name]
            current = topic
            while current.parent_id is not None:
                current = await get_topic(session, current.parent_id)
                if current is None:
                    break
                path.append(current.name)
            path.reverse()
        chat_pane.active_topic = topic
        chat_pane._topic_path = path
        chat_pane.update_status_bar()
        return f"Active topic set to: {topic.name}"

    @tool("set_mode", description="Set the active session mode. Accepted values: 'idle', 'learn', 'review'.")
    @tool_visibility(ToolVisibility.LOW)
    async def set_mode_tool(mode: str, runtime: ToolRuntime) -> str | Command:
        try:
            target = Mode(mode)
        except ValueError:
            return f"Invalid mode '{mode}'. Must be one of: idle, learn, review."
        await chat_pane._set_mode(target, silent=True, source="agent")
        return Command(update={
            "mode": target.value,
            "messages": [ToolMessage(
                content=f"Mode is now: {target.value}",
                tool_call_id=runtime.tool_call_id,
            )],
        })

    @tool("rename_tab", description=(
        "Rename the active chat session tab. Keep the name short — around 20 characters, "
        "2-3 words. The default max tab width is 20 characters (the user can change this)."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def rename_tab_tool(name: str) -> str:
        await chat_pane._cmd_rename(name)
        return f"Tab renamed to: {name}"

    # -----------------------------------------------------------------------
    # User input (interrupt-based)
    # -----------------------------------------------------------------------

    @tool("ask_user_input", description=(
        "Present one or more multiple-choice questions to the user and wait for "
        "their selections. Use this when you need the user to choose between "
        "options before proceeding.\n\n"
        "Each question has a short tab name (1-2 words), a full prompt, and a "
        "list of options. If only one question is provided, a simple choice "
        "widget is shown. Multiple questions are presented as a tabbed widget "
        "where the user answers each in turn."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def ask_user_input_tool(
        questions: list[Question],
    ) -> str:
        if len(questions) == 1:
            q = questions[0]
            result = interrupt({
                "type": "choices",
                "message": q.prompt,
                "options": q.options,
            })
            return f"User selected: {result}"
        else:
            qs = [q.model_dump() for q in questions]
            result = interrupt({
                "type": "multiple_choice",
                "questions": qs,
            })
            # result is dict[str, str] mapping question names to answers
            lines = [f"{name}: {answer}" for name, answer in result.items()]
            return "User selections:\n" + "\n".join(lines)

    @tool("hint_higher_verbosity", description=(
        "Hint to the user that a higher verbosity setting may be needed to properly "
        "answer their query. Use this ONLY in 'terse' verbosity mode when the question "
        "warrants a longer answer. Do NOT use in 'standard', 'verbose', or 'auto' mode."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def hint_higher_verbosity_tool() -> str:
        if chat_pane is not None:
            from rhizome.tui.widgets import HintHigherVerbosity
            chat_pane.post_message(HintHigherVerbosity())
        return "Hint sent."

    return {
        "set_topic": set_topic_tool,
        "set_mode": set_mode_tool,
        "rename_tab": rename_tab_tool,
        "ask_user_input": ask_user_input_tool,
        "hint_higher_verbosity": hint_higher_verbosity_tool,
    }
