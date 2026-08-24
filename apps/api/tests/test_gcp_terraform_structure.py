from pathlib import Path

from scripts.gcp.validate_terraform_structure import inspect_file


def test_current_terraform_file_structure_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "x" "y" {\n  lifecycle { prevent_destroy = true }\n  settings { tier = "x{y}" }\n}\n',
        encoding="utf-8",
    )
    assert inspect_file(path) == []


def test_duplicate_resource_lifecycle_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "x" "y" {\n lifecycle { prevent_destroy = true }\n lifecycle { ignore_changes = [] }\n}\n',
        encoding="utf-8",
    )
    findings = inspect_file(path)
    assert len(findings) == 1
    assert "duplicate lifecycle blocks=2" in findings[0]


def test_unbalanced_hcl_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "x" "y" {\n', encoding="utf-8")
    assert "unclosed opening brace" in inspect_file(path)[0]


def test_comment_braces_do_not_change_structure(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "x" "y" {\n # } {\n lifecycle { prevent_destroy = true }\n /* { } */\n}\n',
        encoding="utf-8",
    )
    assert inspect_file(path) == []
