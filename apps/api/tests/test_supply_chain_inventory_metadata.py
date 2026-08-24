from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/supply_chain_metadata.py"


def _module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("generate_supply_chain_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publisher_metadata_is_exact_version_bound_and_https(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "licenses.json"
    path.write_text(
        json.dumps(
            {
                "schema": "korpus.publisher-license-metadata.v1",
                "records": [
                    {
                        "name": "Demo_Pkg",
                        "version": "1.2.3",
                        "license": "MIT",
                        "evidence_kind": "PYPI_PUBLISHER_METADATA",
                        "source_url": "https://pypi.org/project/demo-pkg/1.2.3/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    records = module.publisher_licenses(path)
    assert ("demo-pkg", "1.2.3") in records
    assert ("demo-pkg", "1.2.4") not in records


def test_publisher_fallback_never_claims_package_is_installed() -> None:
    module = _module()
    publisher = {
        ("demo", "1.0"): {
            "license": "MIT",
            "evidence_kind": "PYPI_PUBLISHER_METADATA",
            "source_url": "https://pypi.org/project/demo/1.0/",
        }
    }
    license_expression, status, evidence = module.component_license("demo", "1.0", {}, publisher)
    assert license_expression == "MIT"
    assert status == module.PUBLISHER_DECLARED
    assert evidence is publisher[("demo", "1.0")]


def test_unknown_version_stays_unresolved_instead_of_reusing_adjacent_license() -> None:
    module = _module()
    publisher = {
        ("demo", "1.0"): {
            "license": "MIT",
            "evidence_kind": "PYPI_PUBLISHER_METADATA",
            "source_url": "https://pypi.org/project/demo/1.0/",
        }
    }
    license_expression, status, evidence = module.component_license("demo", "2.0", {}, publisher)
    assert license_expression is None
    assert status == module.NOT_INSTALLED
    assert evidence is None


def test_inventory_language_never_claims_legal_or_vulnerability_clearance() -> None:
    metadata_source = SCRIPT.read_text(encoding="utf-8")
    inventory_source = (ROOT / "scripts/generate_supply_chain_inventory.py").read_text(
        encoding="utf-8"
    )
    assert "NOT_LEGAL_CLEARANCE" in metadata_source
    assert "Vulnerability status remains UNKNOWN" in inventory_source
