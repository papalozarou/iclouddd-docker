# ------------------------------------------------------------------------------
# This script validates basic documentation integrity for the repository.
#
# The checks stay intentionally narrow and deterministic:
#
# 1. Confirm the key top-level documentation files exist.
# 2. Confirm relative Markdown links resolve to tracked files.
# ------------------------------------------------------------------------------

from __future__ import annotations

from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CONFIGURATION.md",
    REPO_ROOT / "OPERATIONS.md",
    REPO_ROOT / "SCHEDULING.md",
    REPO_ROOT / "TELEGRAM.md",
]
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


# ------------------------------------------------------------------------------
# This function checks that the required top-level docs exist.
#
# Returns: List of validation error strings.
# ------------------------------------------------------------------------------
def check_required_docs() -> list[str]:
    errors: list[str] = []

    for doc_path in DOC_PATHS:
        if doc_path.exists():
            continue

        errors.append(f"Missing required documentation file: {doc_path.name}")

    return errors


# ------------------------------------------------------------------------------
# This function checks that relative Markdown links resolve on disk.
#
# 1. "doc_path" is the Markdown file to validate.
#
# Returns: List of validation error strings.
# ------------------------------------------------------------------------------
def check_markdown_links(doc_path: Path) -> list[str]:
    errors: list[str] = []
    content = doc_path.read_text(encoding="utf-8")

    for raw_target in MARKDOWN_LINK_PATTERN.findall(content):
        target = raw_target.strip()

        if not target:
            continue

        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue

        clean_target = target.split("#", 1)[0]
        target_path = (doc_path.parent / clean_target).resolve()

        if target_path.exists():
            continue

        errors.append(
            f"{doc_path.name}: broken relative link target: {raw_target}"
        )

    return errors


# ------------------------------------------------------------------------------
# This function runs the documentation checks and returns a process status code.
#
# Returns: Zero when checks pass; otherwise one.
# ------------------------------------------------------------------------------
def main() -> int:
    errors = check_required_docs()

    for doc_path in DOC_PATHS:
        if not doc_path.exists():
            continue

        errors.extend(check_markdown_links(doc_path))

    if not errors:
        print("Documentation checks passed.")
        return 0

    for error in errors:
        print(error, file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
