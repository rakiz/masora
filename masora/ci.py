"""`masora ci`: print the packaged reusable CI check workflow template.

CI belongs to the BASE repository's `.github/workflows/`, never to an agent
home — so unlike `masora skill install` / `masora hook install` there is no
automatic installation, only the print (the `masora skill print` idiom): the
maintainer copies the template into the base repo and calls it from its
pull_request workflow.
"""

from __future__ import annotations

from importlib import resources

TEMPLATE_REL = "templates/masora-check.yml"


def template_text() -> str:
    return (resources.files("masora") / TEMPLATE_REL).read_text(encoding="utf-8")


def run(action: str) -> int:
    if action != "print":
        print(f"unknown ci action {action!r} — known actions: print")
        return 1
    text = template_text()
    print(text if text.endswith("\n") else text + "\n", end="")
    return 0
