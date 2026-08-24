#!/usr/bin/env python3
"""Provider-independent Terraform HCL structural admission.

This is a fast offline pre-gate. GitHub-hosted `terraform validate` remains the
provider-schema authority.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_MASKABLE = re.compile(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|#[^\n]*', re.DOTALL)
_RESOURCE = re.compile(r'\bresource\s+"[^"]*"\s+"[^"]*"\s*\{')
_LIFECYCLE = re.compile(r"\blifecycle\s*\{")


def _mask_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.startswith('"') and token.endswith('"'):
        body = "".join("\n" if char == "\n" else " " for char in token[1:-1])
        return f'"{body}"'
    return "".join("\n" if char == "\n" else " " for char in token)


def _masked(text: str) -> str:
    masked = _MASKABLE.sub(_mask_token, text)
    if "/*" in masked:
        raise ValueError("unterminated block comment")
    if masked.count('"') % 2:
        raise ValueError("unterminated string")
    return masked


def _brace_pairs(masked: str) -> tuple[dict[int, int], list[str]]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    errors: list[str] = []
    for pos, char in enumerate(masked):
        if char == "{":
            stack.append(pos)
        elif char == "}" and stack:
            pairs[stack.pop()] = pos
        elif char == "}":
            errors.append(f"unexpected closing brace at byte {pos}")
    errors.extend(f"unclosed opening brace at byte {pos}" for pos in stack)
    return pairs, errors


def _direct_lifecycle_count(masked: str, start: int, end: int) -> int:
    depth = 0
    count = 0
    for match in re.finditer(r"[{}]|\blifecycle\s*\{", masked[start:end]):
        token = match.group(0)
        if token.startswith("lifecycle") and depth == 0:
            count += 1
            depth += 1
        elif token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
    return count


def inspect_file(path: Path) -> list[str]:
    try:
        masked = _masked(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [str(exc)]
    pairs, errors = _brace_pairs(masked)
    for match in _RESOURCE.finditer(masked):
        open_pos = match.end() - 1
        close_pos = pairs.get(open_pos)
        if close_pos is None:
            continue
        count = _direct_lifecycle_count(masked, open_pos + 1, close_pos)
        if count > 1:
            header = re.sub(r"\s+", " ", match.group(0)).rstrip("{").strip()
            errors.append(f"{header}: duplicate lifecycle blocks={count}")
    return errors


def evaluate(root: Path) -> dict[str, object]:
    files = sorted((root / "infra" / "gcp").rglob("*.tf"))
    findings = [
        {"path": str(path.relative_to(root)), "error": error}
        for path in files
        for error in inspect_file(path)
    ]
    return {
        "schema": "korpus.terraform-structure.v1",
        "status": "PASS" if files and not findings else "FAIL",
        "files": len(files),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = evaluate(args.root.resolve())
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
