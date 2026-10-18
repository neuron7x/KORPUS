"""Equivalent Python import spellings must expose the same forbidden edge."""

import pytest

from apps.api.tests import test_architecture as architecture


@pytest.mark.parametrize(
    "statement",
    [
        "from korpus.infrastructure import repository",
        "from korpus import infrastructure",
        "from ..infrastructure import repository",
        "from .. import infrastructure",
        "import korpus.infrastructure.repository as sql",
        "def deferred():\n    from .. import infrastructure",
    ],
)
def test_every_adapter_import_spelling_is_visible(tmp_path, monkeypatch, statement):
    monkeypatch.setattr(architecture, "SRC", tmp_path)
    source = tmp_path / "application" / "probe.py"
    source.parent.mkdir()
    source.write_text(statement, encoding="utf-8")
    assert "infrastructure" in {
        architecture._layer_of_module(module) for module, _ in architecture._imports(source)
    }


@pytest.mark.parametrize(
    "filename,statement",
    [
        ("application/nested/probe.py", "from ... import infrastructure"),
        ("application/nested/__init__.py", "from ... import infrastructure"),
    ],
)
def test_nested_packages_resolve_relative_depth(tmp_path, monkeypatch, filename, statement):
    monkeypatch.setattr(architecture, "SRC", tmp_path)
    source = tmp_path / filename
    source.parent.mkdir(parents=True)
    source.write_text(statement, encoding="utf-8")
    assert "infrastructure" in {
        architecture._layer_of_module(module) for module, _ in architecture._imports(source)
    }


def test_same_layer_relative_import_does_not_become_an_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(architecture, "SRC", tmp_path)
    source = tmp_path / "application" / "probe.py"
    source.parent.mkdir()
    source.write_text("from . import ports", encoding="utf-8")
    assert {
        architecture._layer_of_module(module) for module, _ in architecture._imports(source)
    } == {"application"}


def test_mcp_is_a_transport_layer_not_a_composition_root():
    assert architecture._layer_of_file(architecture.SRC / "mcp" / "server.py") == "mcp"
    assert architecture._layer_of_module("korpus.mcp.server") == "mcp"


def test_domain_cannot_depend_on_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(architecture, "SRC", tmp_path)
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    source = tmp_path / "domain" / "probe.py"
    source.parent.mkdir()
    source.write_text("from korpus.mcp import server", encoding="utf-8")
    with pytest.raises(AssertionError, match="domain imports mcp"):
        architecture.test_no_layer_imports_a_layer_above_it()
