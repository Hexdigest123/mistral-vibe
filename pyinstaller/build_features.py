"""Optional build features for `make build`: a chooser, the uv extras and the PyInstaller hooks of each.

Fork feature (AGENTS.md "Fork features"). To add a feature, add one `Feature` to FEATURES.

    python pyinstaller/build_features.py select   # ask (or take FEATURES=a,b|all|none), save the choice
    python pyinstaller/build_features.py extras   # `--extra x` flags for `uv sync` from the saved choice
    python pyinstaller/build_features.py list     # the features and whether the saved choice has them
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys

CHOICE_FILE = Path(__file__).resolve().parent.parent / ".build-features.json"


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    description: str
    # `[project.optional-dependencies]` extras `uv sync` installs for it.
    extras: tuple[str, ...] = ()
    # Packages PyInstaller collects whole (code, data, native libraries).
    collect_all: tuple[str, ...] = ()
    hidden_imports: tuple[str, ...] = ()
    # What the build host needs besides Python packages, shown with the choice.
    needs: str = ""
    default: bool = False
    extra_notes: tuple[str, ...] = field(default=())


FEATURES: tuple[Feature, ...] = (
    Feature(
        id="voice-agents",
        title="Conversation mode",
        description="Hands-free voice talk with a Mistral voice agent (Ctrl+X t)",
        extras=("voice-agents",),
        collect_all=("livekit", "mistralai.extra.voice_agents"),
        hidden_imports=("pyaudio", "numpy"),
        needs="system PortAudio (Arch: portaudio, Debian: libportaudio2 portaudio19-dev)",
        default=True,
    ),
)


def _by_id() -> dict[str, Feature]:
    return {feature.id: feature for feature in FEATURES}


def saved() -> set[str] | None:
    """The saved choice, or None when nothing was chosen yet."""
    try:
        chosen = json.loads(CHOICE_FILE.read_text())
    except (OSError, ValueError):
        return None
    return {name for name in chosen if name in _by_id()}


def selected() -> list[Feature]:
    """The chosen features: the saved choice, else the defaults."""
    ids = saved()
    if ids is None:
        ids = {feature.id for feature in FEATURES if feature.default}
    return [feature for feature in FEATURES if feature.id in ids]


def parse(value: str) -> set[str]:
    """`all`, `none` or comma-separated ids; an unknown id is an error."""
    words = {word.strip() for word in value.split(",") if word.strip()}
    if words <= {"none"}:
        return set()
    if words == {"all"}:
        return set(_by_id())
    unknown = words - set(_by_id())
    if unknown:
        raise SystemExit(f"unknown build feature: {', '.join(sorted(unknown))}")
    return words


def _ask(current: set[str]) -> set[str]:
    chosen = set(current)
    while True:
        print("\nOptional features to build into this install:\n", file=sys.stderr)
        for number, feature in enumerate(FEATURES, 1):
            mark = "x" if feature.id in chosen else " "
            print(
                f"  {number}. [{mark}] {feature.title}: {feature.description}",
                file=sys.stderr,
            )
            if feature.needs:
                print(f"         needs {feature.needs}", file=sys.stderr)
        print(
            "\nNumber toggles, a all, n none, Enter builds: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        try:
            with open("/dev/tty") as tty:
                answer = tty.readline().strip().lower()
        except OSError:
            return chosen
        if not answer:
            return chosen
        if answer in ("a", "all"):
            chosen = set(_by_id())
        elif answer in ("n", "none"):
            chosen = set()
        else:
            for word in answer.replace(",", " ").split():
                if word.isdigit() and 1 <= int(word) <= len(FEATURES):
                    chosen ^= {FEATURES[int(word) - 1].id}


def select() -> None:
    """FEATURES=... decides without asking; else ask on a terminal; else keep the saved choice."""
    current = {feature.id for feature in selected()}
    preset = os.environ.get("FEATURES")
    if preset is not None:
        chosen = parse(preset)
    elif sys.stdin.isatty() or os.path.exists("/dev/tty"):
        chosen = _ask(current)
    else:
        chosen = current
    CHOICE_FILE.write_text(json.dumps(sorted(chosen)) + "\n")
    names = ", ".join(sorted(chosen)) or "none"
    print(f"Build features: {names}", file=sys.stderr)


def extras_flags() -> str:
    return " ".join(
        f"--extra {extra}" for feature in selected() for extra in feature.extras
    )


def main(argv: list[str]) -> None:
    match argv[1:]:
        case ["select"]:
            select()
        case ["extras"]:
            print(extras_flags())
        case ["list"]:
            have = {feature.id for feature in selected()}
            for feature in FEATURES:
                print(
                    f"{'x' if feature.id in have else ' '} {feature.id}: {feature.title}"
                )
        case _:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
