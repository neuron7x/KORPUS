"""Межа, яку обходить одна велика літера, не є межею.

ВИМІРЯНО 02.09.2026 запитом із інтернету, не читанням:

    /api/v1/documents/ingest  -> 404 від nginx, 146 байт, без `x-request-id`
    /api/v1/Documents/ingest  -> 404 З `x-request-id`,  22 байти

Другий запит ДІЙШОВ ДО ЗАСТОСУНКУ: заголовок ставить FastAPI, nginx його не додає. Те
саме для `/Admin/accounts` і `/Ingestion-Jobs`. Причина — `location ~` замість
`location ~*` у переліку записових маршрутів, тобто РЕГІСТРОЗАЛЕЖНЕ зіставлення.

Найгостріше в цьому не сама вада, а її сусідство: той САМИЙ файл двадцятьма рядками
нижче вживає `~*` для статики (`\\.(?:js|css|json…)$`). Автор знав про різницю між
чутливим і нечутливим зіставленням і застосував нечутливість до менш важливого правила.
Тобто знання було, а перенесення на межу — ні.

Чому тест СТАТИЧНИЙ і додається попри те, що проба вже ходить у великому регістрі
(`verify_public_surface.EDGE_DENIED_ROUTES`): та проба потребує ЖИВОЇ межі й бігає лише
там, де edge піднято. Ця перевірка бігає в `api-test`, тобто на кожному дереві, і не
залежить від того, чи хтось щось розгорнув. Дві дороги до одного твердження — навмисно:
жодна з них не є моделлю іншої.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "deploy/public/nginx.conf"

#: Маршрути, яких публічна особа не може мати ніколи. Якщо перелік у конфізі зміниться,
#: тест не намагається його вгадати — він перевіряє ФОРМУ правила, що їх тримає.
_WRITE_ROUTE_MARKERS = ("admin/", "ingestion-jobs", "documents/ingest")


def _deny_locations(source: str) -> list[str]:
    """Заголовки `location`, чий регекс містить бодай один записовий маршрут."""
    return [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("location")
        and any(marker in line for marker in _WRITE_ROUTE_MARKERS)
    ]


def test_the_write_route_boundary_is_case_insensitive():
    source = CONFIG.read_text(encoding="utf-8")
    boundaries = _deny_locations(source)
    assert boundaries, "у конфізі немає правила, що тримає записові маршрути"
    for rule in boundaries:
        assert re.match(r"location\s+~\*", rule), (
            "межа записових маршрутів зіставляється РЕГІСТРОЗАЛЕЖНО і обходиться однією "
            f"великою літерою: {rule[:90]}"
        )


def test_the_probe_actually_varies_the_case():
    """Негативний контроль на саму пробу: перелік мусить МІСТИТИ великий регістр.

    Проба, що ходить лише в канонічному написанні, не рухає ту змінну, про яку твердить,
    і лишалась би зеленою при регістрозалежній межі — саме так вона й лишалась.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "public_surface", ROOT / "scripts/verify_public_surface.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    routes = [route for _, route in module.EDGE_DENIED_ROUTES]
    varied = [r for r in routes if re.search(r"/v1/[A-Z]", r)]
    assert varied, "проба не має жодного маршруту у великому регістрі"
    assert len(varied) == len(routes) - len(varied), (
        "кожен канонічний маршрут мусить мати рівно один варіант із великою літерою"
    )
