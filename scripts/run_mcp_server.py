#!/usr/bin/env python3
"""Запустити КОРПУС як MCP-інструмент для агента.

Змінні оточення НЕ мають префікса `KORPUS_` навмисно. Застосунок відмовляється
стартувати, побачивши нерозпізнану `KORPUS_*` змінну — і це правильно, бо
описка тихо лишає налаштування на дефолті. Але оператор, який експортує
`KORPUS_MCP_TOKEN` у своєму профілі, зламав би цим ЗАПУСК API. Тому префікс
власний.

    MCP_KORPUS_BASE_URL   http://127.0.0.1:8000 за замовчуванням
    MCP_KORPUS_TOKEN      обов'язковий; токен видає `korpus.cli issue-token`
    MCP_KORPUS_TIMEOUT    секунди, 30 за замовчуванням
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "apps/api/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from korpus.mcp.server import KorpusMcpServer  # noqa: E402
from korpus.mcp.stdio import serve  # noqa: E402
from korpus.mcp.transport import KorpusApi  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30.0


def build_server() -> KorpusMcpServer:
    token = os.getenv("MCP_KORPUS_TOKEN", "").strip()
    if not token:
        # Порожній токен дав би 401 на кожен виклик, і агент прочитав би це як
        # «корпус не має підстав». Відмовляти треба тут, поки причина ще названа.
        raise SystemExit(
            "MCP_KORPUS_TOKEN is required: issue one with `python -m korpus.cli issue-token`"
        )
    timeout = float(os.getenv("MCP_KORPUS_TIMEOUT", str(DEFAULT_TIMEOUT)))
    api = KorpusApi(
        base_url=os.getenv("MCP_KORPUS_BASE_URL", DEFAULT_BASE_URL),
        token=token,
        timeout_seconds=timeout,
    )
    return KorpusMcpServer(api=api)


def main() -> int:
    serve(build_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
