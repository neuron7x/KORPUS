"""Тонкий перехідник до ВЛАСНОГО HTTP-API, а не другий шлях відповіді.

Спокуса була зробити навпаки: підняти сервіс відповіді в тому ж процесі й не
платити за мережу. Це коштувало б трьох речей одразу, і кожна з них — межа,
збудована сьогодні:

- журнал. Подію `answer.completed` пише шлях API; агент, що ходить повз нього,
  не лишає сліду, і `corpus_release` відповіді нема з чим звіряти;
- RLS. Особистість прив'язує брокер на з'єднанні API; у чужому процесі claim'ів
  немає, і запит або бачить усе, або нічого;
- одна тотожність на один предмет. Другий шлях відповіді — це другий набір
  порогів, який розійдеться з першим мовчки.

Тому тут лише HTTP, і жодного рядка доменної логіки.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class TransportFailure(RuntimeError):
    """Запит не дійшов або не повернувся. Це НЕ відповідь «немає підстав»."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        #: Транспортна відмова, названа як «корпус не знає», — найтихіша з підмін:
        #: агент запише у висновок відсутність, якої ніхто не міряв.
        self.retryable = retryable


@dataclass(frozen=True)
class KorpusApi:
    base_url: str
    token: str
    timeout_seconds: float = 30.0

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise TransportFailure(
                f"korpus api {error.code}: {detail}", retryable=error.code >= 500
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransportFailure(f"korpus api unreachable: {error}", retryable=True) from error
        except json.JSONDecodeError as error:
            raise TransportFailure("korpus api returned non-JSON", retryable=False) from error

    def bootstrap(self) -> dict[str, Any]:
        return dict(self._request("GET", "/v1/client/bootstrap"))

    def ask(self, question: str, as_of: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": question}
        if as_of:
            payload["as_of"] = as_of
        return dict(self._request("POST", "/v1/answers", payload))

    def span(self, span_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"/v1/spans/{span_id}"))
