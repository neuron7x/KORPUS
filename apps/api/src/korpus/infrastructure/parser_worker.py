from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from korpus.infrastructure.extraction import extract_pages_from_path


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        pages, method = extract_pages_from_path(
            Path(request["path"]),
            str(request["filename"]),
            str(request["mime_type"]),
            bool(request["ocr_enabled"]),
            str(request["ocr_languages"]),
            max_pdf_pages=int(request["max_pdf_pages"]),
            ocr_total_timeout_seconds=int(request["ocr_total_timeout_seconds"]),
        )
        sys.stdout.write(
            json.dumps(
                {"pages": [asdict(page) for page in pages], "method": method}, ensure_ascii=False
            )
        )
        return 0
    except Exception as exc:
        sys.stderr.write(f"parser error: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
