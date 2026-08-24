import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api/src"))
from korpus.config import Settings  # noqa: E402
from korpus.main import create_app  # noqa: E402

from scripts.openapi_normalization import normalize_openapi  # noqa: E402

DEFAULT = ROOT / "contracts/openapi.json"


def canonical_contract() -> str:
    app = create_app(Settings(environment="test", auth_mode="disabled"))
    contract = json.dumps(
        normalize_openapi(app.openapi()), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return contract + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--path", type=Path, default=DEFAULT)
    args = parser.parse_args()
    path = args.path if args.path.is_absolute() else ROOT / args.path
    actual = canonical_contract()
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        print(path)
        return
    if not path.is_file():
        raise SystemExit(f"OpenAPI contract missing: {path}")
    expected = path.read_text(encoding="utf-8")
    if expected != actual:
        raise SystemExit("OpenAPI contract drift detected; review and regenerate explicitly")
    print("OpenAPI contract matches")


if __name__ == "__main__":
    main()
