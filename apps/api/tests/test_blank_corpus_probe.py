"""Проба нульового входу мала НУЛЬ тестів: усі дев'ять засіяних мутантів вижили.

`probe_blank_corpus.py` виносить вирок про те, чи система відповідає без підстави.
Її власні вирішувачі — `answered` і `verdict` — чисті функції, і жоден рядок їх не
виконував. Наскрізне плече тут теж є і не потребує сервера: недосяжний порт дає
рівно ту транспортну відмову, заради розрізнення якої проба й тримає окремий стан.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/probe_blank_corpus.py"
SPEC = importlib.util.spec_from_file_location("probe_blank_corpus", SCRIPT)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules["probe_blank_corpus"] = PROBE
SPEC.loader.exec_module(PROBE)


def test_two_hundred_with_citations_is_an_answer() -> None:
    assert PROBE.answered({"status": 200, "payload": {"citations": [{"id": "c1"}]}}) is True


def test_spans_are_read_when_citations_are_absent() -> None:
    """Друга назва тієї самої речі: читач, що знає лише `citations`, оголосив би
    відповіддю зі `spans` відмову — і проба зарахувала б її як пройдену."""
    assert PROBE.answered({"status": 200, "payload": {"spans": [{"id": "s1"}]}}) is True


def test_two_hundred_without_citations_is_a_refusal_not_an_answer() -> None:
    assert PROBE.answered({"status": 200, "payload": {"citations": []}}) is False


def test_a_non_two_hundred_is_not_an_answer_even_when_it_carries_citations() -> None:
    """Плече, яке відрізняє `or` від `and` у сторожі: код відповіді вирішує ПЕРШИМ."""
    assert PROBE.answered({"status": 503, "payload": {"citations": [{"id": "c1"}]}}) is False


def test_a_two_hundred_whose_body_is_not_an_object_is_not_an_answer() -> None:
    """`isinstance(..., dict)` стоїть тут не для краси: без нього список у тілі
    відповіді дає AttributeError замість вироку."""
    assert PROBE.answered({"status": 200, "payload": [{"id": "c1"}]}) is False


def test_transport_failure_is_not_an_answer() -> None:
    assert PROBE.answered({"status": PROBE.TRANSPORT_FAILURE, "payload": None}) is False


def test_one_answer_without_a_corpus_fails_the_probe() -> None:
    """Порога немає: одна відповідь на вилученому шарі — уже FAIL."""
    assert PROBE.verdict([True, True], [False, True]) == "FAIL"


def test_answers_with_the_corpus_and_none_without_it_pass() -> None:
    assert PROBE.verdict([True, True], [False, False]) == "PASS"


def test_a_system_that_answers_nothing_at_all_is_unknown_not_pass() -> None:
    """Система, що мовчить завжди, не пройшла пробу — вона позбавила її предмета."""
    assert PROBE.verdict([False, False], [False, False]) == "UNKNOWN"


def test_nothing_measured_is_unknown_not_pass() -> None:
    assert PROBE.verdict([], []) == "UNKNOWN"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_the_script_counts_transport_failures_instead_of_calling_them_measurements(
    tmp_path: Path,
) -> None:
    """Наскрізне плече без сервера.

    Кейс, до якого не дійшов запит, не сміє потрапити в знаменник: `0.0` і «не
    міряли» в теці доказів виглядають однаково. Порт свідомо вільний, тож кожен
    запит — транспортна відмова; правильний облік дає `questions_measured: 0` і
    `transport_failures: 2`, а вирок UNKNOWN із кодом виходу 2.
    """
    questions = tmp_path / "domain_boundary.jsonl"
    questions.write_text(
        "".join(
            json.dumps({"query": q, "stratum": "in_corpus"}, ensure_ascii=False) + "\n"
            for q in ("питання про статут", "питання про наказ")
        ),
        encoding="utf-8",
    )
    out = tmp_path / "blank.json"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base",
            f"http://127.0.0.1:{_free_port()}",
            "--token",
            "t",
            "--questions",
            str(questions),
            "--timeout",
            "2",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
    )
    assert done.returncode == 2, done.stdout + done.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["questions_declared"] == 2
    assert report["questions_measured"] == 0
    assert report["transport_failures"] == 2
    assert report["status"] == "UNKNOWN"


def test_the_script_measures_its_own_stratum_not_the_other_one(tmp_path: Path) -> None:
    """Проба живе на `in_corpus`. Набір, у якому своїх питань НЕМАЄ, мусить дати
    названу відмову, а не мовчазний нуль — і навпаки, набір лише зі своїх питань
    не сміє читатись як порожній."""
    only_out = tmp_path / "out.jsonl"
    only_out.write_text(
        json.dumps({"query": "як налаштувати гаманець", "stratum": "out_of_corpus"}) + "\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base",
            "http://127.0.0.1:1",
            "--token",
            "t",
            "--questions",
            str(only_out),
            "--out",
            str(tmp_path / "o.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
    )
    assert done.returncode == 1, done.stdout + done.stderr
    # Раннє повідомлення друкується з `ensure_ascii` за замовчуванням, тож звіряємо
    # розібраний JSON, а не байти: інакше тест був би про кодування, не про вирок.
    assert json.loads(done.stdout)["why"].startswith("перелік своїх питань порожній")


class _AlwaysAnswers(BaseHTTPRequestHandler):
    """Сервер, який відповідає цитатами НА ВСЕ — і на запит із вилученим корпусом.

    Це стан, заради виявлення якого проба існує: відповідь прийшла з ваг моделі,
    бо підстави в корпусі немає за побудовою.
    """

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps({"citations": [{"id": "c1", "text": "з ваг, не з корпусу"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@contextlib.contextmanager
def _stub_api() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AlwaysAnswers)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_an_answer_on_the_removed_evidence_layer_fails_the_probe_end_to_end(
    tmp_path: Path,
) -> None:
    """Наскрізний вирок, а не лише вирішувачі.

    Без цього плеча облік транспорту можна було інвертувати в обидві сторони і
    нічого не помітити: у прогоні, де ВСЕ падає транспортом, лічильник збігається
    з правильним випадково. Тут запити доходять, тож `transport_failures: 0` і
    `answered_with_blank_corpus: 2` — числа, які не можуть збігтися випадково.
    """
    questions = tmp_path / "domain_boundary.jsonl"
    questions.write_text(
        "".join(
            json.dumps({"query": q, "stratum": "in_corpus"}, ensure_ascii=False) + "\n"
            for q in ("питання про статут", "питання про наказ")
        ),
        encoding="utf-8",
    )
    out = tmp_path / "blank.json"
    with _stub_api() as base:
        done = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--base",
                base,
                "--token",
                "t",
                "--questions",
                str(questions),
                "--timeout",
                "10",
                "--out",
                str(out),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
        )
    assert done.returncode == 1, done.stdout + done.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["transport_failures"] == 0
    assert report["questions_measured"] == 2
    assert report["answered_with_corpus"] == 2
    assert report["answered_with_blank_corpus"] == 2
