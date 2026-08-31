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


surface_rule = _module("scripts/public_operator_surface.py")
surface = _module("scripts/verify_public_surface.py")


# ------------------------------------------------------------ похідна операторська поверхня


def test_operator_surface_is_the_whole_console_not_three_filenames() -> None:
    """Значення, а не лише правило: розбіжність має падати, а не мовчати."""
    assert surface_rule.operator_only(WEB_SOURCE) == {
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
    assert surface_rule.operator_only(tmp_path) == {"console.html", "console.js"}


def test_shared_module_stays_public_when_both_pages_load_it(tmp_path: Path) -> None:
    """Негативний контроль: правило не сміє прибирати те, що вантажить читач."""
    (tmp_path / "index.html").write_text('<script src="/app.js"></script>', encoding="utf-8")
    (tmp_path / "console.html").write_text('<script src="/console.js"></script>', encoding="utf-8")
    (tmp_path / "app.js").write_text('import {x} from "./shared.js";', encoding="utf-8")
    (tmp_path / "console.js").write_text('import {x} from "./shared.js";', encoding="utf-8")
    (tmp_path / "shared.js").write_text("export const x = 1;", encoding="utf-8")
    assert surface_rule.operator_only(tmp_path) == {"console.html", "console.js"}


def test_rule_that_would_withhold_a_reader_essential_refuses(tmp_path: Path) -> None:
    """Помилка, яку найважче помітити: сторінка вийшла б порожньою, а гейт — зеленим."""
    (tmp_path / "index.html").write_text("<p>без скриптів</p>", encoding="utf-8")
    (tmp_path / "console.html").write_text('<script src="/app.js"></script>', encoding="utf-8")
    (tmp_path / "app.js").write_text("// потрібен читачеві", encoding="utf-8")
    try:
        surface_rule.operator_only(tmp_path)
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
    tree = ast.parse((ROOT / "scripts/public_operator_surface.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Set | ast.List | ast.Tuple):
            continue
        names = {item.value for item in node.elts if isinstance(item, ast.Constant)}
        assert not {"console.html", "console.js", "console_rules.js"} & names, (
            "public_operator_surface.py знову тримає вписаний перелік консолі"
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


# ------------------------------------------------------- закриття як математичний об'єкт


def _reference_reachability(edges: dict[str, set[str]], entry: str, nodes: list[str]) -> set[str]:
    """Незалежне означення досяжності: об'єднання степенів матриці суміжності.

    Написано НАВМИСНО іншим способом, ніж обхід у `public_operator_surface`: той —
    пошук у глибину зі списком очікування, цей — булева алгебра над матрицею.
    Спільна залежність між тим, що міряють, і тим, чим міряють, робить згоду
    беззмістовною: розбіжність двох означень має бути видимою як розбіжність
    множин, а не схованою в спільній функції.

    R = ⋃_{k≥0} A^k, обчислене до нерухомої точки; крок k не додає нічого нового
    щонайпізніше при k = |V|, тому цикл скінченний за побудовою.
    """
    index = {name: position for position, name in enumerate(nodes)}
    size = len(nodes)
    adjacency = [[False] * size for _ in range(size)]
    for source, targets in edges.items():
        for target in targets:
            if source in index and target in index:
                adjacency[index[source]][index[target]] = True
    current = [name == entry for name in nodes]
    while True:
        nxt = list(current)
        for row in range(size):
            if not current[row]:
                continue
            for column in range(size):
                if adjacency[row][column]:
                    nxt[column] = True
        if nxt == current:
            return {nodes[position] for position, on in enumerate(nxt) if on}
        current = nxt


def _write_graph(root: Path, nodes: list[str], edges: dict[str, set[str]]) -> None:
    for node in nodes:
        links = "".join(
            f'<script src="/{target}"></script>' for target in sorted(edges.get(node, ()))
        )
        (root / node).write_text(links or "// порожньо", encoding="utf-8")


def test_traversal_is_a_true_transitive_closure_over_every_small_graph(tmp_path: Path) -> None:
    """Вичерпно, не вибірково: усі 256 графів на чотирьох вузлах із ребрами в {a,b}.

    Обхід, що читає лише ОДИН рівень посилань, тут падає негайно: у графі
    index → a → b він не побачив би `b`, тоді як еталон бачить. Саме такий обхід
    оголосив би `console_readonly.js` не операторським, бо його тягне не сама
    сторінка, а `console.js`.
    """
    nodes = ["index.html", "console.html", "a.js", "b.js"]
    sinks = ["a.js", "b.js"]
    checked = 0
    for mask in range(1 << (len(nodes) * len(sinks))):
        edges: dict[str, set[str]] = {}
        bit = 0
        for source in nodes:
            for target in sinks:
                if mask >> bit & 1:
                    edges.setdefault(source, set()).add(target)
                bit += 1
        for name in tmp_path.iterdir():
            name.unlink()
        _write_graph(tmp_path, nodes, edges)
        for entry in ("index.html", "console.html"):
            assert surface_rule._reachable(tmp_path, entry) == _reference_reachability(
                edges, entry, nodes
            ), f"розбіжність означень на масці {mask} для входу {entry}"
        checked += 1
    assert checked == 256


def test_a_reader_link_can_only_shrink_the_operator_surface(tmp_path: Path) -> None:
    """Монотонність у бік, який рятує читача, а не ховає консоль.

    Правило віднімає закриття читача. Тому кожне НОВЕ завантаження з боку читача
    може лише зменшити операторську поверхню — ніколи не збільшити. Помилка в цей
    бік коштує зайвого 404 на файлі, який нікому не потрібен; помилка у зворотний
    бік публікує операторський модуль. Тест тримає саме асиметрію.
    """
    base_edges = {"console.html": {"a.js", "b.js"}}
    nodes = ["index.html", "console.html", "a.js", "b.js"]
    _write_graph(tmp_path, nodes, base_edges)
    before = surface_rule.operator_only(tmp_path)
    assert before == {"console.html", "a.js", "b.js"}

    for name in tmp_path.iterdir():
        name.unlink()
    _write_graph(tmp_path, nodes, {**base_edges, "index.html": {"a.js"}})
    after = surface_rule.operator_only(tmp_path)
    assert after < before, "поява читацького завантаження не зменшила операторську поверхню"
    assert after == {"console.html", "b.js"}
