from __future__ import annotations

import hashlib
import json
from pathlib import Path

from korpus.application.provenance import compute_source_digest
from korpus.application.release_claims import claim_ledger

from scripts.current_truth_admission import (
    blocker_state_checks,
    claim_admission_checks,
    owner_packet_checks,
)
from scripts.current_truth_aliases import alias_checks


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_digest_binds_web_and_ci_release_surfaces(tmp_path: Path) -> None:
    for rel, data in {
        "apps/api/src/korpus/a.py": "x=1\n",
        "apps/web/public/app.js": "export const x=1;\n",
        ".github/workflows/release.yml": "name: release\n",
    }.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
    first = compute_source_digest(tmp_path)
    (tmp_path / "apps/web/public/app.js").write_text("export const x=2;\n", encoding="utf-8")
    second = compute_source_digest(tmp_path)
    (tmp_path / ".github/workflows/release.yml").write_text("name: hardened\n", encoding="utf-8")
    third = compute_source_digest(tmp_path)
    assert len({first, second, third}) == 3


def test_supported_claim_must_resolve_to_current_evidence(tmp_path: Path) -> None:
    release, digest = "v9", "a" * 64
    ledger = tmp_path / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    _write(ledger, {"claims": [{"status": "SUPPORTED", "evidence": "evidence.json"}]})
    _write(
        tmp_path / "evidence.json",
        {"release": release, "source_tree_sha256": "b" * 64, "status": "PASS"},
    )
    assert (
        claim_admission_checks(tmp_path, release, digest)[
            "CLAIM_LEDGER.supported_evidence_resolves"
        ]
        is False
    )
    _write(
        tmp_path / "evidence.json",
        {"release": release, "source_tree_sha256": digest, "status": "PASS"},
    )
    assert (
        claim_admission_checks(tmp_path, release, digest)[
            "CLAIM_LEDGER.supported_evidence_resolves"
        ]
        is True
    )


def test_alias_checks_bind_git_imports_and_package_build(tmp_path: Path) -> None:
    release, artifact = "v9", "KORPUS_v9.zip"
    _write(tmp_path / "apps/api/src/korpus/release.json", {"distribution_artifact": artifact})
    _write(tmp_path / "RELEASE_ENVELOPE.json", {"release": release})
    report = {"release": release}
    _write(tmp_path / "CANONICAL_RELEASE_REPORT.json", report)
    _write(tmp_path / "reports/CANONICAL_RELEASE_REPORT.json", report)
    _write(
        tmp_path / "FULL_SSOT_PACKAGE_RECEIPT.json",
        {"release": release, "package_role": "FULL_SSOT_CANONICAL"},
    )
    _write(tmp_path / "PACKAGE_BUILD.json", {"release": release})
    for name in ("GITHUB_IMPORT.md", "GITLAB_IMPORT.md"):
        (tmp_path / name).write_text(f"{release} {artifact}\n", encoding="utf-8")
    checks = alias_checks(tmp_path, release)
    assert all(checks.values())
    (tmp_path / "GITHUB_IMPORT.md").write_text(f"{release} stale.zip\n", encoding="utf-8")
    assert alias_checks(tmp_path, release)["GITHUB_IMPORT.md.artifact_bound"] is False


def test_release_claims_use_portable_mutation_evidence(tmp_path: Path) -> None:
    release, digest = "v9", "a" * 64
    ledger = claim_ledger(tmp_path, digest, release)
    mutation = next(claim for claim in ledger["claims"] if claim["id"] == "CLM-MUTATION")
    assert mutation["evidence"] == "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
    assert not mutation["evidence"].startswith("var/")


def test_source_integrity_claim_uses_a_bound_verification_report(tmp_path: Path) -> None:
    ledger = claim_ledger(tmp_path, "a" * 64, "v9")
    source = next(claim for claim in ledger["claims"] if claim["id"] == "CLM-SOURCE-INTEGRITY")
    assert source["evidence"] == "reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json"


# ── Пакет власника: єдиний доказ релізу, який доти не звірявся НІЧИМ.
# Виміряно 04.09.2026: `grep -rl OWNER_PILOT_RELEASE_PACKET scripts/ apps/api/ config/
# Makefile` давав порожньо, а сам пакет називав чотири чужі коміти й жодного разу
# кандидата. Механіка боронила машинні артефакти й лишила людський вхід без нагляду.

PACKET = "reports/OWNER_PILOT_RELEASE_PACKET.md"


def _packet(tmp_path: Path, body: str) -> Path:
    target = tmp_path / PACKET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return tmp_path


def test_a_packet_naming_this_candidate_is_bound(tmp_path: Path) -> None:
    """Позитивне плече: пакет, що називає реліз І дайджест дерева, прив'язаний."""
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.7, дерево " + "a" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.present"] is True
    assert checks[f"{PACKET}.release_bound"] is True
    assert checks[f"{PACKET}.source_bound"] is True


def test_a_packet_about_another_tree_is_not_source_bound(tmp_path: Path) -> None:
    """Саме та вада, що була: назва релізу спільна для всіх кандидатів v0.9.7.

    Без дайджесту пакет про попередній коміт виглядав би прив'язаним, і власник
    підписував би стан, якого документ не описує.
    """
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.7, дерево " + "b" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.release_bound"] is True
    assert checks[f"{PACKET}.source_bound"] is False


def test_a_packet_about_another_release_is_not_release_bound(tmp_path: Path) -> None:
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.6, дерево " + "a" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.release_bound"] is False


def test_an_absent_packet_is_absent_not_silently_fine(tmp_path: Path) -> None:
    """Відсутній пакет — це «власнику нема на чому вирішувати», а не «скарг немає».

    Порожній перелік перевірок читався б як згода: `all([])` істинне.
    """
    checks = owner_packet_checks(tmp_path, "v0.9.7", "a" * 64)
    assert checks == {f"{PACKET}.present": False}
    assert checks[f"{PACKET}.present"] is False


def test_empty_release_or_digest_cannot_bind_anything(tmp_path: Path) -> None:
    """Порожній рядок міститься в будь-якому тексті: без цієї сторожі прив'язка
    задовольнялась би тим, що дайджест не обчислили."""
    root = _packet(tmp_path, "# Пакет без жодних міток\n")
    checks = owner_packet_checks(root, "", "")
    assert checks[f"{PACKET}.release_bound"] is False
    assert checks[f"{PACKET}.source_bound"] is False


def test_two_surfaces_under_one_field_name_are_not_compared_by_number(tmp_path: Path) -> None:
    """ВИМІРЯНО 05.09.2026. Поле `source_tree_sha256` носять ДВІ різні поверхні.

    `compute_source_digest` міряє двадцять оголошених доказових шляхів (`evidence_paths`),
    `scripts/source_digest.py` — усе відстежуване дерево (`tracked_tree`). На одному й тому
    самому чистому коміті вони дають різні числа, і це задум: докстрінг першої каже «never
    compare the two», докстрінг другої — «Carry `digest_scope` beside the value and compare
    scopes before hashes».

    Припис лежав у коді й не був виконаний: із 200 артефактів із цим полем `digest_scope`
    ніс РІВНО ОДИН. Читач порівнював числа, не спитавши, чи вони про одну поверхню, — і звіт,
    підписаний однією й перевірений проти другої, падав як «unbound»: повідомлення про зміну
    дерева, коли дерево не змінювалось.

    Твердження тут не про числа, а про ПОРЯДОК: спершу поверхня, потім хеш.
    """
    from scripts.current_truth_contract import report_binding_checks, scope_agrees

    assert scope_agrees({"digest_scope": "evidence_paths"}) is True
    assert scope_agrees({"digest_scope": "tracked_tree"}) is False, "інша поверхня — не згода"
    assert scope_agrees({}) is False, "не назвав поверхні — не довів"

    release, digest = "v9", "a" * 64
    target = tmp_path / "reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json"
    for name in (
        "reports/STANDARDS_CONTROL_MAP_VERIFICATION.json",
        "reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json",
    ):
        _write(tmp_path / name, {"source_tree_sha256": digest, "digest_scope": "evidence_paths"})

    _write(target, {"source_tree_sha256": digest, "digest_scope": "evidence_paths"})
    good = report_binding_checks(tmp_path, release, digest)
    assert good["reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json.source_bound"] is True

    # ТЕ САМЕ число, інша поверхня: збіг хешів тут нічого не доводить.
    _write(target, {"source_tree_sha256": digest, "digest_scope": "tracked_tree"})
    crossed = report_binding_checks(tmp_path, release, digest)
    assert crossed["reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json.scope_named"] is False
    assert crossed["reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json.source_bound"] is False

    # Поверхня названа правильно, число інше — падає з ІНШОЇ причини, і це видно.
    _write(target, {"source_tree_sha256": "b" * 64, "digest_scope": "evidence_paths"})
    drifted = report_binding_checks(tmp_path, release, digest)
    assert drifted["reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json.scope_named"] is True
    assert drifted["reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json.source_bound"] is False


def test_the_final_truth_artifacts_name_their_surface(tmp_path: Path) -> None:
    """Реєстр і журнал претензій — теж читачі одного поля, тож і для них порядок той самий."""
    from scripts.current_truth_contract import final_truth_checks

    release, digest = "v9", "a" * 64
    base = tmp_path / f"reports/release/{release}/final"
    _write(base / "CLAIM_LEDGER.json", {"source_tree_sha256": digest, "release": release})
    _write(
        base / "BLOCKER_REGISTRY.json",
        {"source_tree_sha256": digest, "release": release, "digest_scope": "evidence_paths"},
    )
    checks = final_truth_checks(tmp_path, release, digest)
    assert checks["BLOCKER_REGISTRY.json.source_bound"] is True
    assert checks["CLAIM_LEDGER.json.scope_named"] is False, "поверхні не названо"
    assert checks["CLAIM_LEDGER.json.source_bound"] is False, "число збігається, доказу немає"


def test_the_live_artifacts_in_this_tree_name_their_surface() -> None:
    """Негативний контроль до всіх трьох: поле мусить бути В АРТЕФАКТАХ, не лише у функції.

    Перевірки вище звіряють читача на вигаданих даних. Але контракт читає п'ять СПРАВЖНІХ
    файлів, і якщо виробник колись перестане називати поверхню, кожне твердження вище
    лишиться зеленим.
    """
    import json

    from scripts.current_truth_contract import CURRENT_REPORTS, EVIDENCE_SCOPE

    root = Path(__file__).resolve().parents[3]

    live = [
        *CURRENT_REPORTS,
        *(
            f"reports/release/v0.9.7/final/{name}"
            for name in ("BLOCKER_REGISTRY.json", "CLAIM_LEDGER.json")
        ),
    ]
    unnamed = [
        name
        for name in live
        if json.loads((root / name).read_text(encoding="utf-8")).get("digest_scope")
        != EVIDENCE_SCOPE
    ]
    assert not unnamed, f"артефакти не називають поверхні: {unnamed}"


def test_a_packet_that_names_a_commit_is_refused_even_when_the_digest_is_right(
    tmp_path: Path,
) -> None:
    """Вада, якої `source_bound` не бачить ЗА ПОБУДОВОЮ.

    Виміряно 04.09.2026 на `05246147`: заголовок казав `**КАНДИДАТ:** d2964c6e5386…`,
    кандидатом був `05246147`, а рядок дайджесту був ПРАВИЛЬНИЙ — бо `reports/` не
    входить у `EVIDENCE_SOURCE_PATHS`, тож два різні коміти несуть один дайджест
    джерела. Перевірка підрядком проходила, документ називав не той коміт.

    Обидва плеча тут в ОДНОМУ тесті навмисно: доказ у тому, що `source_bound` лишається
    істинним, поки п'ята перевірка червона. Порізно кожне плече виглядало б як згода.
    """
    digest = "a" * 64
    body = (
        "# Пакет власника — приватний пілот KORPUS v0.9.7\n\n"
        "**КАНДИДАТ:** `d2964c6e5386bb8ab7f6cfcec3af855a876bbf8d`\n"
        f"**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`\n"
    )
    checks = owner_packet_checks(_packet(tmp_path, body), "v0.9.7", digest)
    assert checks[f"{PACKET}.source_bound"] is True
    assert checks[f"{PACKET}.no_unverifiable_candidate"] is False


def test_a_packet_bound_only_by_digest_is_accepted(tmp_path: Path) -> None:
    """Позитивне плече п'ятої перевірки: без рядка про коміт пакет прийнятний.

    Дайджест — єдина тотожність, яку проза в дереві здатна тримати істинною: `reports/`
    поза `EVIDENCE_SOURCE_PATHS`, тож запис у пакет його не зсуває. Коміт документ
    назвати не може взагалі — його власна правка створює новий.
    """
    digest = "a" * 64
    body = (
        "# Пакет власника — приватний пілот KORPUS v0.9.7\n\n"
        f"**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`\n"
        "**Кандидат** — коміт, який несе цей дайджест; його називає захищений тег.\n"
    )
    checks = owner_packet_checks(_packet(tmp_path, body), "v0.9.7", digest)
    assert checks[f"{PACKET}.source_bound"] is True
    assert checks[f"{PACKET}.no_unverifiable_candidate"] is True


def test_the_refusal_is_about_the_claim_not_about_hex_anywhere(tmp_path: Path) -> None:
    """Негативний контроль на сам контроль: заборонено ТВЕРДЖЕННЯ, не шістнадцяткове.

    Без цього перевірка червоніла б від будь-якої згадки коміта в прозі — а пакет мусить
    мати право процитувати історичний коміт, не оголошуючи його кандидатом. Перевірка,
    що падає на цитаті, змусила б наступного автора цитати прибрати, і документ став би
    біднішим заради зеленого кольору.
    """
    digest = "a" * 64
    body = (
        "# Пакет власника — приватний пілот KORPUS v0.9.7\n\n"
        f"**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`\n\n"
        "Вада знайдена на `d2964c6e5386bb8ab7f6cfcec3af855a876bbf8d` і закрита на\n"
        "наступному коміті; КАНДИДАТ згадується тут як слово, не як прив'язка.\n"
    )
    checks = owner_packet_checks(_packet(tmp_path, body), "v0.9.7", digest)
    assert checks[f"{PACKET}.no_unverifiable_candidate"] is True


# ── Реєстр блокерів: прив'язка до ДЕРЕВА не визначає його ЗМІСТУ.
# Стани реєстру виводяться з reports/PRODUCTION_HARD_PREDICATES.json, а `reports/`
# навмисно поза `source_tree_sha256` — інакше доказ знецінював би себе щоразу, як його
# переписують. Наслідок: реєстр лишався «прив'язаним», коли змінився його вхід.
# Виміряно 04.09.2026 на f311e83a: реєстр зібрано о 13:20, доказ перезібрано о 19:50,
# обидва в ТОМУ САМОМУ коміті; перезбирання на незміненому дереві перевело 7 блокерів
# EXTERNAL_REQUIRED → CLOSED_ANCHORED, і жоден гейт цього не побачив.

REGISTRY = "reports/release/v0.9.7/final/BLOCKER_REGISTRY.json"
PREDICATES = "reports/PRODUCTION_HARD_PREDICATES.json"


def _registry_tree(
    tmp_path: Path, on_disk: object, recorded_of: object | None, *, drop_field: bool = False
) -> Path:
    """Дерево, де реєстр записує дайджест `recorded_of`, а на диску лежить `on_disk`."""
    body = json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n"
    (tmp_path / PREDICATES).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / PREDICATES).write_text(body, encoding="utf-8")
    registry: dict[str, object] = {
        "schema": "korpus.blocker-registry.v2",
        "release": "v0.9.7",
        "source_tree_sha256": "a" * 64,
        "hard_predicate_report_current": True,
        "internal_executable_unresolved": 0,
    }
    if not drop_field:
        recorded = json.dumps(recorded_of, ensure_ascii=False, indent=2) + "\n"
        registry["evidence_sha256"] = {
            PREDICATES: hashlib.sha256(recorded.encode("utf-8")).hexdigest()
        }
    _write(tmp_path / REGISTRY, registry)
    return tmp_path


_HONEST = {"release": "v0.9.7", "externally_satisfied": 7, "states": []}
_POISONED = {"release": "v0.9.7", "externally_satisfied": 0, "states": [{"id": "x"}]}


def test_a_registry_built_from_other_evidence_than_the_tree_holds_is_refused(
    tmp_path: Path,
) -> None:
    """Саме та вада: той самий шлях, та сама прив'язка до дерева, ІНШИЙ зміст входу.

    Обидва плеча в одному тесті навмисно. Доказ не в тому, що нова перевірка червона,
    а в тому, що всі СТАРІ лишаються зеленими — тобто без неї стан проходив цілком.
    """
    root = _registry_tree(tmp_path, on_disk=_POISONED, recorded_of=_HONEST)
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.source_bound_current"] is True
    assert checks["BLOCKER_REGISTRY.hard_predicate_report_current"] is True
    assert checks["BLOCKER_REGISTRY.internal_executable_unresolved_zero"] is True
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_a_registry_built_from_the_evidence_present_is_admitted(tmp_path: Path) -> None:
    """Позитивне плече: перевірка мусить уміти й ПРОЙТИ, інакше вона не вимір."""
    root = _registry_tree(tmp_path, on_disk=_HONEST, recorded_of=_HONEST)
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is True


def test_a_registry_that_names_no_inputs_is_unmeasured_not_agreed(tmp_path: Path) -> None:
    """Порожній перелік входів читається як «не виміряно»: `all([])` істинне."""
    root = _registry_tree(tmp_path, on_disk=_HONEST, recorded_of=_HONEST, drop_field=True)
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_an_empty_input_map_is_unmeasured_not_agreed(tmp_path: Path) -> None:
    """ПОРОЖНІЙ словник входів — не те саме, що відсутнє поле, і не згода.

    Знайдено мутацією 05.09.2026, не читанням: зняття умови `or not recorded` не вбило
    жодного тесту, бо контроль вище прибирає ПОЛЕ (`None`), а не лишає `{}`. Без цього
    тесту твердження «порожній перелік читається як не виміряно» було текстом у
    докстрінгу, якого жоден прогін не перевіряв — `all([])` істинне, і саме ця форма
    вже коштувала нам гейта раніше.
    """
    root = _registry_tree(tmp_path, on_disk=_HONEST, recorded_of=_HONEST)
    registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    registry["evidence_sha256"] = {}
    _write(root / REGISTRY, registry)
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_a_recorded_input_that_is_missing_from_the_tree_is_refused(tmp_path: Path) -> None:
    """Зниклий вхід — відмова, а не «нема на що скаржитись»."""
    root = _registry_tree(tmp_path, on_disk=_HONEST, recorded_of=_HONEST)
    (root / PREDICATES).unlink()
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_a_digest_recorded_for_another_path_does_not_vouch_for_this_one(
    tmp_path: Path,
) -> None:
    """Підміна ШЛЯХУ входу: дайджест правильний, але не про той файл, з якого зібрано."""
    root = _registry_tree(tmp_path, on_disk=_HONEST, recorded_of=_HONEST)
    registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    digest = next(iter(registry["evidence_sha256"].values()))
    registry["evidence_sha256"] = {"reports/SOMETHING_ELSE.json": digest}
    _write(root / REGISTRY, registry)
    checks = blocker_state_checks(root, "v0.9.7", "a" * 64)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False
