from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from manifest_paths import source_included  # noqa: E402


def _included(relative: str) -> bool:
    """Одне означення того, що є джерелом, — канонічне `manifest_paths.source_included`.

    Тут стояв ДРУГИЙ перелік виключень, і він розходився з каноном на СІМИ шляхах:
    `.verdict-ledger.jsonl`, `CANONICAL_RELEASE_REPORT.{json,md}`, `PACKAGE_BOUNDARY.md`,
    `PACKAGE_BUILD.json`, `FULL_SSOT_PACKAGE_RECEIPT.json` і `LINEAGE/.../SOURCE_MANIFEST.json`
    — тобто рівно ті файли, які пише сам цикл релізу. Наслідок той самий, що вже полагодили
    для `source_digest`: корінь системного маніфесту зсувався щоразу, коли перезаписувався
    будь-який реліз-звіт, БЕЗ жодної зміни коду, і це число вже лежить у `var/eval-report.json`
    через `run_evals.py`, звідки його бере збірка забезпечення.

    Сторож проти повернення другого переліку існував і був зелений: він читав
    `scripts/source_digest.py` і не бачив цього файла. Перевірка проти другого визначення,
    яка дивиться лише в одне місце, зелена саме тоді, коли друге визначення є.
    Знайдено пошуком розбіжностей 06.09.2026.
    """
    return source_included(Path(relative))


def _git_tracked_files() -> tuple[list[Path], str] | None:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    values = listed.stdout.decode("utf-8").split("\0")
    return ([ROOT / value for value in values if value and _included(value)], commit)


def _archive_files() -> tuple[list[Path], str]:
    manifest_path = ROOT / "SOURCE_MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError("neither Git metadata nor SOURCE_MANIFEST.json is available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    root_hash = manifest.get("root_sha256")
    if not isinstance(records, list) or not isinstance(root_hash, str) or len(root_hash) != 64:
        raise RuntimeError("invalid source manifest")
    paths: list[Path] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise RuntimeError("invalid source manifest record")
        relative = record["path"]
        if not _included(relative):
            continue
        path = (ROOT / relative).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise RuntimeError(f"source-manifest file is missing or unsafe: {relative}")
        expected = record.get("sha256")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected != actual:
            raise RuntimeError(f"source-manifest hash mismatch: {relative}")
        paths.append(path)
    return paths, f"archive:{root_hash}"


def tracked_files() -> tuple[list[Path], str]:
    return _git_tracked_files() or _archive_files()


def build() -> dict[str, object]:
    paths, source_revision = tracked_files()
    entries: list[dict[str, object]] = []
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix()
        payload = path.read_bytes()
        entries.append(
            {"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "korpus-system-manifest-v1",
        "commit": source_revision,
        "files": entries,
        "file_count": len(entries),
        "manifest_root_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("var/system-manifest.json"))
    args = parser.parse_args()
    result = build()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
