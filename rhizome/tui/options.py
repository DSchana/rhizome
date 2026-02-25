"""Option definitions, persistence, validation, and pub/sub for the TUI.

Provides a hierarchical options system with scoped inheritance (Root → Session),
validation, JSONC persistence, and async subscriber notifications.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from enum import IntEnum
from pathlib import Path
from typing import Any, overload

from rhizome.config import get_options_path


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

EventHandler = Callable[[Any, Any], Awaitable[None]]


class OptionScope(IntEnum):
    """Scope at which an option can be set."""

    Root = 0
    Session = 1


# ---------------------------------------------------------------------------
# OptionSpec hierarchy
# ---------------------------------------------------------------------------


class OptionSpec:
    """Base option specification: name, scope, default, help text."""

    def __init__(
        self,
        name: str,
        scope: OptionScope,
        default: Any,
        help: str,
    ) -> None:
        self.name = name
        self.resolved_name: str = name  # overwritten by metaclass
        self.scope = scope
        self.default = default
        self.help = help

    def validate(self, value: Any) -> Any:
        """Validate and return the (possibly coerced) value, or raise ValueError."""
        return value

    def from_string(self, raw: str) -> Any:
        """Parse a string into the option's native type."""
        return raw.strip()

    def jsonc_comment(self) -> str:
        """Return JSONC comment text (without leading ``//``)."""
        return self.help


class ChoicesOptionSpec(OptionSpec):
    """Option constrained to a fixed set of choices."""

    def __init__(
        self,
        name: str,
        scope: OptionScope,
        default: Any,
        help: str,
        choices: list[Any],
    ) -> None:
        super().__init__(name, scope, default, help)
        self.choices = choices

    def validate(self, value: Any) -> Any:
        if value not in self.choices:
            raise ValueError(f"Must be one of: {', '.join(str(c) for c in self.choices)}")
        return value

    def from_string(self, raw: str) -> Any:
        return self.validate(raw.strip())

    def jsonc_comment(self) -> str:
        return f"{self.help}\n// Choices: {', '.join(str(c) for c in self.choices)}"


class ConditionalChoicesOptionSpec(OptionSpec):
    """Option whose available choices depend on the current value of another option."""

    def __init__(
        self,
        name: str,
        scope: OptionScope,
        help: str,
        condition: OptionSpec,
        choices: dict[Any, list[Any]],
        defaults: dict[Any, Any],
    ) -> None:
        self.condition = condition
        self._choices = choices
        self.defaults = defaults
        default = defaults[condition.default]
        super().__init__(name, scope, default, help)

    def validate(self, value: Any, *, condition_value: Any = None) -> Any:
        """Validate *value* against the choices for *condition_value*.

        When *condition_value* is ``None`` (e.g. during JSONC load), accept any
        value present in *any* branch.
        """
        if condition_value is None:
            all_values = [v for branch in self._choices.values() for v in branch]
            if value not in all_values:
                raise ValueError(
                    f"Must be one of: {', '.join(str(c) for c in all_values)}"
                )
        else:
            valid = self._choices.get(condition_value, [])
            if value not in valid:
                raise ValueError(
                    f"Must be one of: {', '.join(str(c) for c in valid)}"
                )
        return value

    def choices_for(self, condition_value: Any) -> list[Any]:
        """Return the choices list for a given condition value."""
        return self._choices.get(condition_value, [])

    def default_for(self, condition_value: Any) -> Any:
        """Return the default for a given condition value."""
        return self.defaults[condition_value]

    def from_string(self, raw: str) -> Any:
        return raw.strip()

    def jsonc_comment(self) -> str:
        lines = [self.help]
        for cond, choices in self._choices.items():
            lines.append(f"// {cond}: {', '.join(str(c) for c in choices)}")
        return "\n".join(lines)


class IntRangeOptionSpec(OptionSpec):
    """Option constrained to an integer range."""

    def __init__(
        self,
        name: str,
        scope: OptionScope,
        default: int,
        help: str,
        min: int,
        max: int,
    ) -> None:
        super().__init__(name, scope, default, help)
        self.min = min
        self.max = max

    def validate(self, value: Any) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected integer, got {value!r}")
        if v < self.min or v > self.max:
            raise ValueError(f"Must be between {self.min} and {self.max}")
        return v

    def from_string(self, raw: str) -> int:
        return self.validate(raw.strip())

    def jsonc_comment(self) -> str:
        return f"{self.help} ({self.min}-{self.max})"


# ---------------------------------------------------------------------------
# OptionNamespace
# ---------------------------------------------------------------------------


class OptionNamespace:
    """Marker base for nested option groups.

    Subclass this inside an ``Options`` class and set ``name = "..."``
    to create a dotted namespace (e.g. ``agent.model``).
    """

    name: str
    resolved_name: str = ""


# ---------------------------------------------------------------------------
# Metaclass
# ---------------------------------------------------------------------------


def _collect_specs(
    namespace: type,
    prefix: str,
    target: list[OptionSpec],
) -> None:
    """Recursively walk *namespace* and wire up resolved names."""
    for attr_name in list(vars(namespace)):
        obj = getattr(namespace, attr_name)
        if isinstance(obj, OptionSpec):
            obj.resolved_name = f"{prefix}.{obj.name}" if prefix else obj.name
            target.append(obj)
        elif isinstance(obj, type) and issubclass(obj, OptionNamespace) and obj is not OptionNamespace:
            ns_name = getattr(obj, "name", attr_name.lower())
            obj.resolved_name = f"{prefix}.{ns_name}" if prefix else ns_name
            _collect_specs(obj, obj.resolved_name, target)


class OptionsMeta(type):
    """Metaclass that walks class attrs to build a flat spec registry."""

    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
        cls = super().__new__(mcs, name, bases, namespace)
        specs: list[OptionSpec] = []
        _collect_specs(cls, "", specs)
        cls._all_specs = specs  # type: ignore[attr-defined]
        return cls


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


class Options(metaclass=OptionsMeta):
    """Hierarchical, scoped option store with pub/sub and JSONC persistence.

    **Class-level**: ``OptionSpec`` and ``OptionNamespace`` members define the
    schema (wired by ``OptionsMeta``).

    **Instance-level**: holds ``_values``, manages subscriptions and
    parent/child links.
    """

    # ---- Schema (class-level) ----

    Theme = ChoicesOptionSpec(
        name="theme",
        scope=OptionScope.Root,
        default="textual-dark",
        help="Textual color theme",
        choices=[
            "textual-dark",
            "textual-light",
            "nord",
            "gruvbox",
            "catppuccin-mocha",
            "textual-ansi",
            "dracula",
            "tokyo-night",
            "monokai",
            "flexoki",
            "catppuccin-latte",
            "solarized-light",
            "solarized-dark",
            "rose-pine",
            "rose-pine-moon",
            "rose-pine-dawn",
            "atom-one-dark",
            "atom-one-light",
        ],
    )

    TabMaxLength = IntRangeOptionSpec(
        name="tab_max_length",
        scope=OptionScope.Root,
        default=20,
        help="Maximum characters for tab names",
        min=10,
        max=50,
    )

    class Agent(OptionNamespace):
        name = "agent"

        Provider = ChoicesOptionSpec(
            name="provider",
            scope=OptionScope.Root,
            default="anthropic",
            help="LLM provider",
            choices=["anthropic", "openai"],
        )

        Model = ConditionalChoicesOptionSpec(
            name="model",
            scope=OptionScope.Session,
            help="LLM model for the agent",
            condition=Provider,
            choices={
                "anthropic": [
                    "claude-opus-4-6",
                    "claude-sonnet-4-6",
                    "claude-haiku-4-5",
                ],
                "openai": [
                    "gpt-5.2",
                    "gpt-5-mini",
                    "gpt-5-nano",
                ],
            },
            defaults={
                "anthropic": "claude-opus-4-6",
                "openai": "gpt-5-mini",
            },
        )

    # ---- Instance ----

    def __init__(self, scope: OptionScope, parent: Options | None = None) -> None:
        self._scope = scope
        self._parent = parent
        self._children: list[Options] = []
        self._values: dict[str, Any] = {}
        self._subscribers: dict[OptionSpec, list[EventHandler]] = {}
        if parent is not None:
            parent._children.append(self)
        if scope == OptionScope.Root:
            for s in self.spec():
                self._values[s.resolved_name] = s.default

        # Auto-subscribe: when a condition option changes, reset dependents
        for s in self.spec():
            if isinstance(s, ConditionalChoicesOptionSpec):

                async def _on_condition_changed(
                    old: Any, new: Any, dep: ConditionalChoicesOptionSpec = s
                ) -> None:
                    current = self.get(dep)
                    valid = dep.choices_for(new)
                    if current not in valid:
                        await self.set(dep, dep.defaults[new], flush=True)

                self.subscribe(s.condition, _on_condition_changed)

    # -- Read --

    def get(self, spec: OptionSpec) -> Any:
        """Resolve a value: local override → parent chain → default."""
        if spec.resolved_name in self._values:
            return self._values[spec.resolved_name]
        if self._parent is not None:
            return self._parent.get(spec)
        return spec.default

    # -- Write --

    async def set(self, spec: OptionSpec, value: Any, *, flush: bool = True) -> None:
        """Validate and set *value*, notifying subscribers."""
        if spec.scope < self._scope:
            raise ValueError(
                f"Cannot set {spec.resolved_name} at {self._scope.name} scope "
                f"(minimum scope: {spec.scope.name})"
            )
        old = self.get(spec)
        if isinstance(spec, ConditionalChoicesOptionSpec):
            condition_value = self.get(spec.condition)
            value = spec.validate(value, condition_value=condition_value)
        else:
            value = spec.validate(value)
        self._values[spec.resolved_name] = value
        if old != value:
            for listener in self._subscribers.get(spec, []):
                await listener(old, value)
            await self._propagate_to_children(spec, old, value)
        if flush:
            self.flush()

    async def reset(self, spec: OptionSpec, *, flush: bool = True) -> None:
        """Remove a local override (session) or reset to default (root)."""
        if self._scope == OptionScope.Root:
            await self.set(spec, spec.default, flush=flush)
        else:
            old = self.get(spec)
            self._values.pop(spec.resolved_name, None)
            new = self.get(spec)
            if old != new:
                for listener in self._subscribers.get(spec, []):
                    await listener(old, new)
                await self._propagate_to_children(spec, old, new)
            if flush:
                self.flush()

    async def _propagate_to_children(
        self, spec: OptionSpec, old: Any, new: Any
    ) -> None:
        for child in self._children:
            if spec.resolved_name not in child._values:
                for listener in child._subscribers.get(spec, []):
                    await listener(old, new)
                await child._propagate_to_children(spec, old, new)

    # -- Subscriptions --

    @overload
    def subscribe(self, key: OptionSpec, listener: EventHandler) -> None: ...
    @overload
    def subscribe(self, key: OptionSpec, listener: list[EventHandler]) -> None: ...
    @overload
    def subscribe(self, key: dict[OptionSpec, EventHandler | list[EventHandler]]) -> None: ...  # type: ignore[override]

    def subscribe(self, key, listener=None):  # type: ignore[override]
        if isinstance(key, dict):
            for spec, handlers in key.items():
                if isinstance(handlers, list):
                    self._subscribers.setdefault(spec, []).extend(handlers)
                else:
                    self._subscribers.setdefault(spec, []).append(handlers)
        elif isinstance(listener, list):
            self._subscribers.setdefault(key, []).extend(listener)
        else:
            self._subscribers.setdefault(key, []).append(listener)

    def unsubscribe(self, spec: OptionSpec, listener: EventHandler) -> None:
        listeners = self._subscribers.get(spec, [])
        try:
            listeners.remove(listener)
        except ValueError:
            pass

    def detach(self) -> None:
        """Remove this instance from parent's children list."""
        if self._parent is not None:
            try:
                self._parent._children.remove(self)
            except ValueError:
                pass
            self._parent = None

    # -- Spec registry --

    @classmethod
    def spec(cls) -> list[OptionSpec]:
        """Flat list of all ``OptionSpec`` instances defined on the class."""
        return list(cls._all_specs)  # type: ignore[attr-defined]

    # -- JSONC persistence --

    def flush(self) -> None:
        """Write values to the JSONC config file (root scope only)."""
        if self._scope != OptionScope.Root:
            return
        path = get_options_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = ["{"]
        specs = self.spec()
        for i, s in enumerate(specs):
            for comment_line in s.jsonc_comment().splitlines():
                if comment_line.startswith("//"):
                    lines.append(f"    {comment_line}")
                else:
                    lines.append(f"    // {comment_line}")
            value = self._values.get(s.resolved_name, s.default)
            json_val = json.dumps(value)
            comma = "," if i < len(specs) - 1 else ""
            lines.append(f"    {json.dumps(s.resolved_name)}: {json_val}{comma}")
            if i < len(specs) - 1:
                lines.append("")
        lines.append("}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @classmethod
    def load(cls) -> Options:
        """Load from the JSONC config file, returning a Root-scope instance."""
        instance = cls(OptionScope.Root)
        path = get_options_path()
        if not path.exists():
            return instance
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(_strip_comments(raw))
        except (json.JSONDecodeError, OSError):
            return instance

        spec_map = {s.resolved_name: s for s in cls.spec()}
        for key, val in data.items():
            s = spec_map.get(key)
            if s is None:
                continue
            try:
                instance._values[s.resolved_name] = s.validate(val)
            except (ValueError, TypeError):
                pass  # keep default
        return instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Remove ``//`` comment lines from JSONC text."""
    return "\n".join(
        line for line in text.splitlines()
        if not re.match(r"^\s*//", line)
    )


def parse_jsonc(text: str) -> dict[str, Any]:
    """Parse a JSONC string, validating values against the spec registry."""
    data = json.loads(_strip_comments(text))
    spec_map = {s.resolved_name: s for s in Options.spec()}
    result: dict[str, Any] = {}
    for key, val in data.items():
        s = spec_map.get(key)
        if s is not None:
            result[key] = s.validate(val)
    return result
