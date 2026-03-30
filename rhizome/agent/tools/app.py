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

    @tool("update_app_state", description=(
        "Update one or more pieces of app state in a single call. All parameters "
        "are optional — only provided values are applied.\n\n"
        "- topic_id: Set the active topic for this chat session.\n"
        "- clear_topic: Clear the active topic (takes precedence over topic_id).\n"
        "- tab_name: Rename the active chat session tab. Keep it short — around "
        "20 characters, 2-3 words.\n"
        "- hint_higher_verbosity: Hint to the user that a higher verbosity setting "
        "may be needed. Use ONLY in 'terse' verbosity mode."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def update_app_state_tool(
        topic_id: int | None = None,
        clear_topic: bool = False,
        tab_name: str | None = None,
        hint_higher_verbosity: bool = False,
    ) -> str:
        results: list[str] = []

        if clear_topic:
            if chat_pane is not None:
                chat_pane.active_topic = None
                chat_pane._topic_path = []
                chat_pane.update_status_bar()
            results.append("Active topic cleared.")
        elif topic_id is not None:
            if chat_pane is None:
                results.append("Chat pane not available.")
            else:
                async with session_factory() as session:
                    topic = await get_topic(session, topic_id)
                    if topic is None:
                        results.append(f"Topic {topic_id} not found.")
                    else:
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
                        results.append(f"Active topic set to: {topic.name}")

        if tab_name is not None:
            if chat_pane is not None:
                await chat_pane._cmd_rename(tab_name)
            results.append(f"Tab renamed to: {tab_name}")

        if hint_higher_verbosity:
            if chat_pane is not None:
                from rhizome.tui.widgets import HintHigherVerbosity
                chat_pane.post_message(HintHigherVerbosity())
            results.append("Higher verbosity hint sent.")

        if not results:
            return "No updates requested."

        return " ".join(results)

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

    return {
        "update_app_state": update_app_state_tool,
        "set_mode": set_mode_tool,
        "ask_user_input": ask_user_input_tool,
    }
