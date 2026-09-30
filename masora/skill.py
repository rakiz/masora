"""`masora skill`: install or print the packaged agent skill.

The skill lives inside the package (`masora/skills/masora/SKILL.md`, one
canonical copy shipped by the wheel) and is installed into DETECTED
agent-framework skills directories under the user's home — copy-install only:
masora never writes into a code repo. Overwriting on re-run IS the update
path.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

FRAMEWORK_DIRS: tuple[tuple[str, str], ...] = (
    (".claude", ".claude/skills/masora"),
    (".config/opencode", ".config/opencode/skills/masora"),
)


def _skill_text() -> str:
    return (resources.files("masora") / "skills/masora/SKILL.md").read_text(encoding="utf-8")


def run(action: str, home: Path | None = None) -> int:
    home = Path.home() if home is None else home
    if action == "print":
        text = _skill_text()
        print(text if text.endswith("\n") else text + "\n", end="")
        return 0
    return _install(home)


def _install(home: Path) -> int:
    text = _skill_text()
    installed = 0
    for marker, target_rel in FRAMEWORK_DIRS:
        if not (home / marker).is_dir():
            continue
        target = home / target_rel
        existed = (target / "SKILL.md").is_file()
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(text, encoding="utf-8")
        print(f"{'updated' if existed else 'installed'}: {target / 'SKILL.md'}")
        installed += 1
    if not installed:
        print(
            "no agent-framework directory found in the home (looking for ~/.claude or"
            " ~/.config/opencode) — pipe the content wherever your mechanism needs it:"
            " masora skill print"
        )
    return 0
