from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from vibe.cli.autocompletion.fuzzy import fuzzy_match
from vibe.cli.textual_ui.constants import UNPINNED_ACTIVE_MODEL
from vibe.cli.textual_ui.shortcut_hints import shortcut, shortcut_hint
from vibe.cli.textual_ui.widgets.navigable_option_list import NavigableOptionList
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.vscode_compat import VscodeCompatInput

# Option id for the "Default" (unpinned) row. Kept distinct from any model alias
# and non-empty so ``OptionList``'s truthiness guard still fires on select.
DEFAULT_OPTION_ID = "\x00default"


@dataclass(frozen=True)
class ModelOption:
    """A selectable model: ``alias`` is persisted, ``display_name`` is shown."""

    alias: str
    display_name: str
    provider: str = ""


@dataclass(frozen=True)
class _PickerEntry:
    """One row of the picker: ``fuzzy_text`` is what the search matches."""

    option_id: str
    label: str
    provider: str
    fuzzy_text: str
    is_current: bool
    hint: str = ""


def _build_option_text(label: str, is_current: bool, *, hint: str = "") -> Text:
    text = Text(no_wrap=True)
    marker = "› " if is_current else "  "
    text.append(marker, style="green" if is_current else "")
    text.append(label, style="bold" if is_current else "")
    if hint:
        text.append(f"  {hint}", style="dim")
    return text


class ModelPickerApp(Container):
    """Model picker bottom app: fzf-style search over the configured models."""

    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    class ModelSelected(Message):
        def __init__(self, alias: str) -> None:
            self.alias = alias
            super().__init__()

    class Cancelled(Message):
        pass

    def __init__(
        self,
        models: list[ModelOption],
        current_model: str,
        *,
        is_pinned: bool,
        default_display_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(id="modelpicker-app", **kwargs)
        self._models = models
        self._current_model = current_model
        self._is_pinned = is_pinned
        self._default_display_name = default_display_name
        self._query = ""

    def _is_alias_current(self, alias: str) -> bool:
        return self._is_pinned and alias == self._current_model

    def _entries_for_query(self, query: str) -> list[_PickerEntry]:
        """Fuzzy-filter the Default row plus all models, best matches first."""
        candidates: list[_PickerEntry] = [
            _PickerEntry(
                option_id=DEFAULT_OPTION_ID,
                label="Default",
                provider="",
                fuzzy_text=f"default {self._default_display_name}",
                is_current=not self._is_pinned,
                hint=f"(currently {self._default_display_name})",
            ),
            *(
                _PickerEntry(
                    option_id=model.alias,
                    label=model.display_name,
                    provider=model.provider,
                    fuzzy_text=f"{model.display_name} {model.alias} {model.provider}",
                    is_current=self._is_alias_current(model.alias),
                )
                for model in self._models
            ),
        ]
        if not query:
            return candidates
        scored: list[tuple[float, int, _PickerEntry]] = []
        for position, entry in enumerate(candidates):
            match = fuzzy_match(query, entry.fuzzy_text)
            if match.matched:
                scored.append((match.score, -position, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _, _, entry in scored]

    def _option(self, entry: _PickerEntry) -> Option:
        return Option(
            _build_option_text(
                entry.label, entry.is_current, hint=entry.provider or entry.hint
            ),
            id=entry.option_id,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="modelpicker-content"):
            yield NoMarkupStatic("Select Model", classes="modelpicker-title")
            yield VscodeCompatInput(
                placeholder="Search models...", id="modelpicker-search", compact=True
            )
            yield NavigableOptionList(
                *map(self._option, self._entries_for_query("")),
                id="modelpicker-options",
            )
            yield NoMarkupStatic(
                shortcut_hint(
                    f"{shortcut('Type')} Search  {shortcut('↑↓')} Navigate  "
                    f"{shortcut('Enter')} Select  {shortcut('Esc')} Cancel"
                ),
                classes="modelpicker-help",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        # Pre-select the current choice: the pinned model, else the Default row.
        highlighted = 0
        if self._is_pinned:
            for index, entry in enumerate(self._entries_for_query("")):
                if entry.option_id == self._current_model:
                    highlighted = index
                    break
        option_list.highlighted = highlighted
        self.query_one(VscodeCompatInput).focus()

    def on_input_changed(self, event: VscodeCompatInput.Changed) -> None:
        if event.input.id != "modelpicker-search":
            return
        self._query = event.value
        self._refresh_options()

    def on_input_submitted(self, _event: VscodeCompatInput.Submitted) -> None:
        self.action_select()

    def on_key(self, event: events.Key) -> None:
        """Steer navigation from the search input, fzf-style, keeping focus."""
        if not isinstance(self.screen.focused, VscodeCompatInput):
            return
        match event.key:
            case "up":
                self._move_highlight(-1)
            case "down":
                self._move_highlight(1)
            case _:
                return
        event.prevent_default()
        event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        alias = (
            UNPINNED_ACTIVE_MODEL
            if event.option.id == DEFAULT_OPTION_ID
            else event.option.id
        )
        self.post_message(self.ModelSelected(alias))

    def action_select(self) -> None:
        option_list = self.query_one(OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        try:
            option = option_list.get_option_at_index(highlighted)
        except IndexError:
            return
        if option.id is None:
            return
        alias = UNPINNED_ACTIVE_MODEL if option.id == DEFAULT_OPTION_ID else option.id
        self.post_message(self.ModelSelected(alias))

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())

    def _refresh_options(self) -> None:
        option_list = self.query_one(OptionList)
        highlighted_id = self._highlighted_option_id(option_list)
        option_list.clear_options()
        for option in map(self._option, self._entries_for_query(self._query)):
            option_list.add_option(option)
        if highlighted_id is not None:
            for index in range(option_list.option_count):
                if option_list.get_option_at_index(index).id == highlighted_id:
                    option_list.highlighted = index
                    return
        option_list.highlighted = 0

    def _move_highlight(self, delta: int) -> None:
        option_list = self.query_one(OptionList)
        count = option_list.option_count
        if not count:
            return
        current = option_list.highlighted or 0
        option_list.highlighted = (current + delta) % count

    @staticmethod
    def _highlighted_option_id(option_list: OptionList) -> str | None:
        option = option_list.highlighted_option
        if option is None or option.id is None:
            return None
        return str(option.id)
