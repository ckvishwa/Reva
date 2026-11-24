"""CI change classifier: decide whether the build and test lanes must run.

Prints the changed files and writes ``code=true`` or ``code=false`` to ``$GITHUB_OUTPUT``.

``code=false`` only when every changed file is documentation that no test, tool or build reads:

* Markdown at the repository root (README.md, CLAUDE.md, CONTRIBUTING.md, ...)
* a directory's own ``README.md``
* anything under ``docs/`` except the spec pack ``docs/spec/``

``docs/spec/`` always counts as code: ``contracts/`` must match its ``08_CONTRACTS`` copy and
tests read it. Any error, an empty diff, or an event that is not a pull request or a push with a
known parent also counts as code, so the lanes run when in doubt.

Inputs (environment): ``EVENT`` (pull_request | push), ``PR_BASE``, ``PUSH_BEFORE``.
"""

from __future__ import annotations

import os
import subprocess
import sys

ZERO = "0" * 40


def is_docs_only_path(path: str) -> bool:
    """True when a change to ``path`` cannot affect any build or test lane."""
    path = path.replace("\\", "/")
    if path.startswith("docs/"):
        return not path.startswith("docs/spec/")
    name = path.rsplit("/", 1)[-1]
    if "/" not in path:
        return name.lower().endswith(".md")
    return name == "README.md"


def needs_code_lanes(paths: list[str]) -> bool:
    """True unless there is at least one path and every path is documentation."""
    return not paths or not all(is_docs_only_path(p) for p in paths)


def changed_paths(event: str, pr_base: str, push_before: str) -> list[str] | None:
    """Changed files for this event, or None when they cannot be determined."""
    if event == "pull_request" and pr_base:
        spec = f"{pr_base}...HEAD"
    elif event == "push" and push_before and push_before != ZERO:
        spec = f"{push_before}..HEAD"
    else:
        return None
    result = subprocess.run(  # noqa: S603 - fixed argv; the SHAs come from the GitHub event
        ["git", "diff", "--name-only", "-z", spec],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [p for p in result.stdout.decode("utf-8", "replace").split("\0") if p]


def main() -> int:
    paths = changed_paths(
        os.environ.get("EVENT", ""),
        os.environ.get("PR_BASE", ""),
        os.environ.get("PUSH_BEFORE", ""),
    )
    if paths is None:
        print("changed files unknown: running every lane")
        code = True
    else:
        for path in paths:
            print(("docs  " if is_docs_only_path(path) else "code  ") + path)
        code = needs_code_lanes(paths)
    print(f"code={str(code).lower()}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"code={str(code).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
