"""Публічна поверхня: твердження мусить бути не ширшим за правило, що його стереже.

Три виконавці незалежно тримали один і той самий перелік із трьох імен файлів, тоді
як твердження в кожному з них було про КОНСОЛЬ. Поверхня виросла до восьми файлів,
жоден перелік не виріс, і 31.08.2026 публічний edge віддавав `console.css`,
`console_accounts.js`, `console_mutations.js`, `console_readonly.js` — по 200 і зі
справжнім вмістом. Тести нижче тримають не наслідок («ці чотири файли закриті»), а
причину: перелік мусить бути ПОХІДНИМ, а другої копії не мусить існувати.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = ROOT / "apps/web/public"
EDGE_TEMPLATE = ROOT / "deploy/public/nginx.conf"
SERVE_SCRIPT = ROOT / "scripts/serve_public.sh"


def _module(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = _module("scripts/deploy_public_web.py")
surface = _module("scripts/verify_public_surface.py")


# ------------------------------------------------------------ похідна операторська поверхня


def test_operator_surface_is_the_whole_console_not_three_filenames() -> None:
    """Значення, а не лише правило: розбіжність має падати, а не мовчати."""
    assert deploy.operator_only(WEB_SOURCE) == {
        "console.html",
        "console.css",
        "console.js",
        "console_rules.js",
        "console_accounts.js",
        "console_mutations.js",
        "console_readonly.js",
        "contract.js",
    }


def test_navigation_link_to_the_console_does_not_make_the_console_public(tmp_path: Path) -> None:
    """Пастка, яка знищила б правило мовчки.

    `index.html` містить `<a href="/console.html">Консоль</a>`. Якби перехід рахувався
    завантаженням, закриття читача поглинуло б консоль, різниця стала б порожньою — і
    правило оголосило б, що операторського немає взагалі, тобто впустило б усе.
    """
    (tmp_path / "index.html").write_text(
        '<a href="/console.html">Консоль</a><script src="/app.js"></script>', encoding="utf-8"
    )
    (tmp_path / "console.html").write_text('<script src="/console.js"></script>', encoding="utf-8")
    (tmp_path / "console.js").write_text("// operator", encoding="utf-8")
    (tmp_path / "app.js").write_text("// reader", encoding="utf-8")
    assert deploy.operator_only(tmp_path) == {"console.html", "console.js"}


def test_shared_module_stays_public_when_both_pages_load_it(tmp_path: Path) -> None:
    """Негативний контроль: правило не сміє прибирати те, що вантажить читач."""
    (tmp_path / "index.html").write_text('<script src="/app.js"></script>', encoding="utf-8")
    (tmp_path / "console.html").write_text('<script src="/console.js"></script>', encoding="utf-8")
    (tmp_path / "app.js").write_text('import {x} from "./shared.js";', encoding="utf-8")
    (tmp_path / "console.js").write_text('import {x} from "./shared.js";', encoding="utf-8")
    (tmp_path / "shared.js").write_text("export const x = 1;", encoding="utf-8")
    assert deploy.operator_only(tmp_path) == {"console.html", "console.js"}


def test_rule_that_would_withhold_a_reader_essential_refuses(tmp_path: Path) -> None:
    """Помилка, яку найважче помітити: сторінка вийшла б порожньою, а гейт — зеленим."""
    (tmp_path / "index.html").write_text("<p>без скриптів</p>", encoding="utf-8")
    (tmp_path / "console.html").write_text('<script src="/app.js"></script>', encoding="utf-8")
    (tmp_path / "app.js").write_text("// потрібен читачеві", encoding="utf-8")
    try:
        deploy.operator_only(tmp_path)
    except ValueError as error:
        assert "app.js" in str(error)
    else:  # pragma: no cover - падіння тесту саме тут і є суть
        raise AssertionError("правило прибрало обов'язковий файл читача і не відмовилось")


# ------------------------------------------------------------------ жодної другої копії


def test_no_executor_keeps_its_own_list_of_console_filenames() -> None:
    """Причина, а не наслідок: другий перелік розійдеться з першим мовчки.

    Саме так це й сталося — три виконавці, три однакові переліки, усі три відстали.
    """
    # Хвороба — саме ЗБІРКА імен, а не згадка про них: пояснення, чому правило таке,
    # має право називати файли, а виконуваний перелік — ні.
    tree = ast.parse((ROOT / "scripts/deploy_public_web.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Set | ast.List | ast.Tuple):
            continue
        names = {item.value for item in node.elts if isinstance(item, ast.Constant)}
        assert not {"console.html", "console.js", "console_rules.js"} & names, (
            "deploy_public_web.py знову тримає вписаний перелік консолі"
        )

    shell = "\n".join(
        line
        for line in SERVE_SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "console_rules.js" not in shell, "serve_public.sh знову тримає перелік імен"
    assert "console.html" not in shell, "serve_public.sh знову тримає перелік імен"


# ------------------------------------------------------------------------------ межа


def test_edge_binds_loopback_because_that_is_what_it_claims() -> None:
    """Контейнер іде з `--network host`, тож `listen 8081;` означало 0.0.0.0."""
    template = EDGE_TEMPLATE.read_text(encoding="utf-8")
    assert "listen 127.0.0.1:8081;" in template
    assert "\n    listen 8081;" not in template


def test_console_rule_covers_the_surface_not_one_filename() -> None:
    template = EDGE_TEMPLATE.read_text(encoding="utf-8")
    assert "location ^~ /console {" in template
    assert "location = /console.html {" not in template


def test_missing_asset_says_absent_rather_than_serving_the_page_under_its_name() -> None:
    """`try_files ... /index.html` віддавав 200 із HTML на запит скрипта."""
    template = EDGE_TEMPLATE.read_text(encoding="utf-8")
    assert "try_files $uri =404;" in template


def test_write_routes_stop_at_the_edge_and_audit_deliberately_does_not() -> None:
    """Розділення навмисне, і саме воно найлегше зникає при редагуванні.

    Записові маршрути мусить спинити межа, бо відмова застосунку настає після читання
    тіла. `/v1/audit/*` — навпаки: панель трасування читача їх кличе, і чесна
    відповідь — 403 від ролі. Межа, що закриє й їх, підмінить відмову на «нема».
    """
    denial = next(
        line
        for line in EDGE_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("location ~ ^/api/")
    )
    for route in ("documents/ingest", "ingestion-jobs", "review", "rescission", "admin/"):
        assert route in denial, f"межа перестала спиняти {route}"
    assert "audit" not in denial, "межа почала підміняти відмову ролі на 404 для audit"


# --------------------------------------------------------------------------- сам гейт


def test_gate_reddens_on_every_defect_separately() -> None:
    """Негативні контролі гейта — частина набору, а не окрема команда, яку забудуть."""
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_public_surface.py"), "--selftest"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_unknown_never_counts_as_pass() -> None:
    """Спостереження, якого не сталося, не доводить нічого."""
    assert surface.verdict(surface.assess({})) == "UNKNOWN"
    assert surface.verdict([]) == "UNKNOWN"
    assert (
        surface.verdict(
            [
                {"check": "a", "verdict": "PASS", "detail": ""},
                {"check": "b", "verdict": "UNKNOWN", "detail": ""},
            ]
        )
        == "UNKNOWN"
    )


def test_fail_outranks_unknown() -> None:
    assert (
        surface.verdict(
            [
                {"check": "a", "verdict": "UNKNOWN", "detail": ""},
                {"check": "b", "verdict": "FAIL", "detail": ""},
            ]
        )
        == "FAIL"
    )
