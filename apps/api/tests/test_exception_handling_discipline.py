"""A broad `except` may fail closed or record; it may not return success.

`TECHNICAL_DEBT_V5.md` carries "removal or narrowing of broad exception handlers in
critical paths" as open engineering debt. Reading all fourteen of them showed something
different from what the entry implies: every one already re-raises, degrades to a
conservative value, or records the failure. The debt is not the handlers — it is that
nothing holds them to it, so the next one written can swallow silently and no test,
gate or review artefact will say a word.

The property is therefore stated over the tree rather than over today's fourteen
sites. A handler for `Exception`, `BaseException` or a bare `except` must do at least
one of:

  * re-raise — the failure keeps travelling;
  * return a value that cannot be mistaken for success (False, None, a non-zero exit
    code) — the caller sees degradation;
  * record the failure through a logger, metric or stderr write — somebody can find
    out that it happened.

`pass`, or returning a success value, is the one shape that is refused: it converts a
fault into evidence of health, which is the failure mode this repository has found in
its gates, its reports and its aggregator, and would find in its runtime next.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (ROOT / "apps/api/src/korpus", ROOT / "scripts")
BROAD = {"Exception", "BaseException"}

#: names that mean "the failure was written down somewhere a human can reach"
RECORDING = ("log", "warn", "error", "exception", "observe", "record", "write", "print", "emit")


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = {node.id for node in ast.walk(handler.type) if isinstance(node, ast.Name)}
    return bool(names & BROAD)


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _records(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func).lower()
            if any(marker in rendered for marker in RECORDING):
                return True
    return False


#: Стани, які не можна сплутати з успіхом. Перелік ЗАКРИТИЙ і оголошений тут, а не
#: виведений із коду: назви станів — відкрита множина, і матчер по ній пускав би все,
#: що містить схоже слово. Порівняння йде по ЦІЛОМУ сегменту імені (розбитому по
#: не-літерах), тож `no_errors_expected` не читається як `ERROR`.
NON_SUCCESS_SEGMENTS = frozenset(
    {"FAILED", "FAILURE", "REJECTED", "ERROR", "UNKNOWN", "DENIED", "UNAVAILABLE", "INVALID"}
)


def _names_a_failure(value: ast.expr) -> bool:
    """Чи називає повернений вираз стан відмови ДОСЛІВНО.

    Правило дозволяє «повернути значення, яке не сплутати з успіхом», але детектор
    бачив лише константи, тож `return early_result(InvocationOutcome.FAILED, …)` —
    деградація у вигляді виклику — читалась як мовчазне глушіння. Це хиба детектора,
    не коду: він міряв ФОРМУ повернення, а не властивість, яку охороняє.

    Приймається лише те, де стан названо: атрибут перелічення (`InvocationOutcome.FAILED`)
    або рядок коду помилки (`"AUDIT_APPEND_FAILED"`). Виклик, що нічого не називає,
    лишається відмовою — невідоме не є дозволом.
    """
    for node in ast.walk(value):
        segments: list[str] = []
        if isinstance(node, ast.Attribute):
            segments = re.split(r"[^A-Za-z]+", node.attr.upper())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            segments = re.split(r"[^A-Za-z]+", node.value.upper())
        elif isinstance(node, ast.Name):
            segments = re.split(r"[^A-Za-z]+", node.id.upper())
        if set(segments) & NON_SUCCESS_SEGMENTS:
            return True
    return False


def _returns_only_non_success(handler: ast.ExceptHandler) -> bool:
    """True when every `return` in the handler yields a value meaning "not ok"."""
    returns = [node for node in ast.walk(handler) if isinstance(node, ast.Return)]
    if not returns:
        return False
    for node in returns:
        value = node.value
        if value is None:
            continue  # bare `return` — the caller gets None
        if isinstance(value, ast.Constant):
            constant = value.value
            # `True` is an int in Python, so an `isinstance(..., int)` test admits it —
            # which is how the first version of this rule passed while a handler
            # returned True. Ordered so bool is decided before int.
            if constant is True:
                return False
            if constant is False or constant is None:
                continue
            if isinstance(constant, int) and constant != 0:
                continue  # a non-zero exit code is a failure the caller can see
            return False
        if _names_a_failure(value):
            continue
        return False
    return True


#: Єдиний спосіб для широкого обробника НЕ деградувати й НЕ записати: назвати доказ,
#: що збій не доходить до виклику. Не вільний пропуск — гейт перевіряє, що названий файл
#: існує. Потреба з'явилась із телеметрією: вона оголошена втратною, у цьому дереві немає
#: логування взагалі (жодного `logging` в `apps/api/src/korpus`), а канал запису цієї
#: підсистеми — аудит рішення, до якого збій ЕКСПОРТЕРА не належить. Виняток без імені
#: доказу був би тим самим мовчазним глушінням, лише з коментарем.
LOSSY_MARKER = re.compile(r"LOSSY-BY-CONTRACT:\s*(?P<proof>[A-Za-z0-9_./-]+\.py)")
TESTS_ROOT = ROOT / "apps/api/tests"


def _lossy_contract_proof(path: str, line: int, source: dict[str, list[str]]) -> str | None:
    """Ім'я доказу, названого поруч із обробником, якщо такий файл справді існує."""
    if path not in source:
        source[path] = (ROOT / path).read_text(encoding="utf-8").splitlines()
    lines = source[path]
    window = lines[max(0, line - 2) : line + 12]
    for text in window:
        found = LOSSY_MARKER.search(text)
        if found and (TESTS_ROOT / Path(found.group("proof")).name).is_file():
            return found.group("proof")
    return None


def _handlers() -> list[tuple[str, int, ast.ExceptHandler]]:
    found: list[tuple[str, int, ast.ExceptHandler]] = []
    for root in SOURCES:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and _is_broad(node):
                    found.append((str(path.relative_to(ROOT)), node.lineno, node))
    return found


def _broad_suppressions() -> list[tuple[str, int, str]]:
    """`with suppress(Exception)` — той самий сліпий обробник, лише іншим вузлом AST.

    Знайдено 06.09.2026 незалежним аудитом: правило вище обходить лише
    `ast.ExceptHandler`, тож `try/except Exception: pass` воно карає, а семантично
    тотожний `with contextlib.suppress(Exception):` не бачить зовсім. Наслідок гірший
    за пропущений випадок: автофікс `ruff SIM105` перетворює перше на друге, тобто
    ЛІНТЕР МОВЧКИ ВИМИКАЄ ЦЕЙ ГЕЙТ. Два правила дерева конфліктували, і конфлікт
    розв'язувався на користь того, яке нічого не міряє.

    Вузькі `suppress(OSError)` тут ні до чого — карається лише той самий клас
    широти, що й у `_is_broad`.
    """
    found: list[tuple[str, int, str]] = []
    for root in SOURCES:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.With):
                    continue
                for item in node.items:
                    call = item.context_expr
                    if not isinstance(call, ast.Call):
                        continue
                    name = getattr(call.func, "attr", getattr(call.func, "id", ""))
                    if name != "suppress":
                        continue
                    caught = {getattr(arg, "id", "") for arg in call.args}
                    if caught & {"Exception", "BaseException"}:
                        found.append(
                            (str(path.relative_to(ROOT)), node.lineno, ", ".join(sorted(caught)))
                        )
    return found


def test_a_broad_suppress_is_judged_like_a_broad_handler() -> None:
    """Інакше `ruff --fix` знімає правило, не змінивши жодної поведінки."""
    source: dict[str, list[str]] = {}
    offenders = [
        f"{path}:{line} suppress({caught})"
        for path, line, caught in _broad_suppressions()
        if not _lossy_contract_proof(path, line, source)
    ]
    assert not offenders, (
        "ці місця глушать усе через contextlib.suppress — семантично це той самий "
        f"сліпий обробник, лише невидимий для правила вище: {offenders}"
    )


def test_there_are_broad_handlers_to_judge() -> None:
    """The dual. A rule over an empty set is a rule that has never been applied."""
    assert len(_handlers()) >= 10, (
        "no broad exception handlers found — either the tree changed shape or this "
        "test is looking in the wrong place, and either way it is asserting nothing"
    )


def test_no_broad_handler_turns_a_fault_into_evidence_of_health() -> None:
    source: dict[str, list[str]] = {}
    offenders = [
        f"{path}:{line}"
        for path, line, handler in _handlers()
        if not (
            _reraises(handler)
            or _records(handler)
            or _returns_only_non_success(handler)
            or _lossy_contract_proof(path, line, source)
        )
    ]
    assert not offenders, (
        "these handlers catch everything and neither re-raise, degrade, record, nor name "
        f"a proof that the failure never reaches the caller: {offenders}"
    )


def test_a_lossy_contract_must_name_a_proof_that_exists() -> None:
    """Негативний контроль: виняток, що вказує в порожнечу, винятком не є."""
    source = {
        "apps/api/tests/test_exception_handling_discipline.py": [
            "# LOSSY-BY-CONTRACT: test_that_was_never_written.py",
        ]
    }
    assert (
        _lossy_contract_proof("apps/api/tests/test_exception_handling_discipline.py", 1, source)
        is None
    )


def test_a_lossy_contract_naming_a_real_proof_is_accepted() -> None:
    source = {"x": ["# LOSSY-BY-CONTRACT: test_capability_gateway_observability_isolation.py"]}
    assert _lossy_contract_proof("x", 1, source) is not None


def test_a_returned_call_that_names_a_failure_state_counts_as_degradation() -> None:
    """Позитивний бік розширеного детектора."""
    tree = ast.parse(
        "try:\n    pass\nexcept Exception:\n"
        "    return early_result(InvocationOutcome.FAILED, 'AUDIT_APPEND_FAILED')\n"
    )
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert _returns_only_non_success(handler)


def test_a_returned_call_that_names_nothing_is_still_refused() -> None:
    """Негативний контроль: без нього дозвіл вище пускав би будь-який виклик."""
    tree = ast.parse("try:\n    pass\nexcept Exception:\n    return build(frame, guard)\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _returns_only_non_success(handler)


def test_a_failure_word_inside_a_longer_word_is_not_a_failure_state() -> None:
    """Сегмент, а не підрядок: інакше `no_errors_expected` читалось би як ERROR."""
    tree = ast.parse("try:\n    pass\nexcept Exception:\n    return build(noerrors=True)\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _returns_only_non_success(handler)


def test_a_returned_success_constant_is_still_refused() -> None:
    tree = ast.parse("try:\n    pass\nexcept Exception:\n    return True\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _returns_only_non_success(handler)


def test_no_bare_except_hides_which_failure_occurred() -> None:
    """`except:` also catches KeyboardInterrupt and SystemExit."""
    bare = [f"{path}:{line}" for path, line, handler in _handlers() if handler.type is None]
    assert not bare, f"bare `except:` swallows KeyboardInterrupt and SystemExit as well: {bare}"


def test_no_broad_handler_is_an_empty_body() -> None:
    """`except Exception: pass` is the shape the whole rule exists to refuse."""
    silent = [
        f"{path}:{line}"
        for path, line, handler in _handlers()
        if all(isinstance(statement, ast.Pass) for statement in handler.body)
    ]
    assert not silent, f"these handlers discard the failure entirely: {silent}"
