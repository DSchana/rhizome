"""Inline TUI widget for editing options."""

from __future__ import annotations

import re
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static

from rhizome.tui.options import (
    ChoicesOptionSpec,
    ConditionalChoicesOptionSpec,
    IntRangeOptionSpec,
    OptionScope,
    OptionSpec,
    Options,
)

# ---------------------------------------------------------------------------
# Widget builders: OptionSpec type → widget factory
# ---------------------------------------------------------------------------

WIDGET_BUILDERS: dict[type[OptionSpec], Any] = {
    ChoicesOptionSpec: lambda spec, val, wid, **kw: Select(
        [(str(c), c) for c in spec.choices], value=val, id=wid
    ),
    ConditionalChoicesOptionSpec: lambda spec, val, wid, **kw: Select(
        [(str(c), c) for c in spec.choices_for(kw["condition_value"])],
        value=val,
        id=wid,
    ),
    IntRangeOptionSpec: lambda spec, val, wid, **kw: Input(
        str(val), placeholder=f"{spec.min}-{spec.max}", id=wid, type="integer"
    ),
}


def _sanitize_id(resolved_name: str) -> str:
    """Turn a dotted resolved name into a valid Textual widget ID.

    Widget IDs may only contain letters, numbers, underscores, or hyphens
    and must not begin with a number.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", resolved_name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return f"opt-{sanitized}"


def _build_widget(
    spec: OptionSpec, value: Any, widget_id: str, options: Options | None = None
) -> Widget:
    builder = WIDGET_BUILDERS.get(type(spec))
    if builder is not None:
        kwargs: dict[str, Any] = {}
        if isinstance(spec, ConditionalChoicesOptionSpec) and options is not None:
            kwargs["condition_value"] = options.get(spec.condition)
        return builder(spec, value, widget_id, **kwargs)
    return Input(str(value), id=widget_id)


class OptionsEditor(Widget):
    """Inline editor for viewing/modifying options."""

    DEFAULT_CSS = """
    OptionsEditor {
        height: auto;
        padding: 1 2;
        background: $surface;
        border: tall $accent;
    }
    OptionsEditor #options-title {
        text-style: bold;
        margin-bottom: 1;
    }
    OptionsEditor .option-label {
        margin-top: 1;
        color: $text-muted;
    }
    OptionsEditor Select {
        width: 40;
    }
    OptionsEditor Input {
        width: 40;
    }
    OptionsEditor #options-done {
        margin-top: 1;
        width: auto;
    }
    """

    class Done(Message):
        """Posted when the user clicks Done."""

    def __init__(self, options: Options, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._options = options
        # Build a map from widget_id → spec for event handling
        self._widget_specs: dict[str, OptionSpec] = {}

    def compose(self) -> ComposeResult:
        scope_label = "root" if self._options._scope == OptionScope.Root else "session"

        with Vertical():
            yield Static(f"Options ({scope_label})", id="options-title")

            for spec in Options.spec():
                # Only show specs settable at this scope
                if spec.scope < self._options._scope:
                    continue

                wid = _sanitize_id(spec.resolved_name)
                self._widget_specs[wid] = spec
                current = self._options.get(spec)

                yield Label(f"{spec.help}  [{spec.resolved_name}]", classes="option-label")
                yield _build_widget(spec, current, wid, self._options)

            yield Button("Done", id="options-done", variant="primary")

    def on_mount(self) -> None:
        """Subscribe to condition specs so dependent widgets update in-place."""
        for spec in Options.spec():
            if not isinstance(spec, ConditionalChoicesOptionSpec):
                continue

            async def _update_dependent(
                old: Any, new: Any, dep: ConditionalChoicesOptionSpec = spec
            ) -> None:
                wid = _sanitize_id(dep.resolved_name)
                try:
                    select = self.query_one(f"#{wid}", Select)
                except Exception:
                    return
                choices = dep.choices_for(new)
                select.set_options([(str(c), c) for c in choices])
                new_val = self._options.get(dep)
                if new_val in choices:
                    select.value = new_val
                else:
                    select.value = choices[0] if choices else Select.BLANK

            self._options.subscribe(spec.condition, _update_dependent)

    def _spec_for_widget(self, widget_id: str | None) -> OptionSpec | None:
        """Look up the OptionSpec associated with a widget, if any."""
        if widget_id is None or not widget_id.startswith("opt-"):
            return None
        return self._widget_specs.get(widget_id)

    def on_select_changed(self, event: Select.Changed) -> None:
        spec = self._spec_for_widget(event.select.id)

        if spec is None or event.value == Select.BLANK:
            return

        self._set_option(spec, event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        spec = self._spec_for_widget(event.input.id)

        if spec is None:
            return

        # Validate eagerly so we can revert the input widget on failure
        # (the worker would swallow the exception otherwise).
        try:
            val = spec.validate(event.value)
        except ValueError:
            event.input.value = str(self._options.get(spec))
            return

        event.input.value = str(val)
        self._set_option(spec, val)

    def _set_option(self, spec: OptionSpec, value: Any) -> None:
        """Set an option value via the Options pub/sub system."""

        async def _do_set() -> None:
            await self._options.set(spec, value)

        self.run_worker(_do_set())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "options-done":
            self.post_message(self.Done())
