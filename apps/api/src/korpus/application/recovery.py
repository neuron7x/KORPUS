"""Classify what a recovery drill actually measured.

`docs/runbooks/BACKUP_RESTORE.md` has said "Record restore duration against the
declared RTO" since v5. Nothing recorded it. The CI job proved that a backup can be
taken, encrypted, restored and verified — which is a different claim from "service
can be back inside a stated time, having lost at most a stated interval". A restore
that succeeds after six hours passes every check this repository had.

Two failure modes are guarded here, and they are not the same:

*Absence.* No drill, or a drill with no provenance, must not read as a pass. The
aggregator asks whether the measurement exists and carries what makes it meaningful —
how much data, on what engine, how long — before it looks at any number.

*Overstatement.* A number measured on a two-row CI fixture describes a two-row CI
fixture. The same shape already bit TEVV, where a calibration figure from a fixture
was reported as if it came from the corpus, so the same defence applies: the report
declares its scale class, and the declaration is checked against the provenance it
carries rather than believed. A fixture cannot promote itself by editing a string.

What is deliberately *not* here: a verdict on whether the measured RTO is acceptable.
No RTO or RPO objective has been declared for KORPUS by anyone entitled to declare
one, and `SLO_AND_RELEASE_POLICY_V5.md` prohibits inventing the number. That gap is
recorded as an admission ground with an owner (§2.9), not as an engineering predicate
that would either block every release or, worse, pass against a threshold this file
made up.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.recovery_contracts import recovery_numeric_problem, recovery_scale_counts

MISSING = "MISSING"
INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"
OVERSTATED_SCALE = "OVERSTATED_SCALE"
#: Втрата, більша за ВІКНО, яке навчання створило навмисно. Стан окремий і б'є решту:
#: зламане відновлення на фікстурному масштабі лишається зламаним відновленням.
UNEXPLAINED_LOSS = "UNEXPLAINED_LOSS"
FIXTURE_SCALE = "FIXTURE_SCALE"
MEASURED = "MEASURED"

FIXTURE = "ci-fixture"
PRODUCTION_LIKE = "production-like"

# Required because each one is what makes the duration mean anything. A restore time
# without the size restored, the engine that restored it and the rows it ended with is
# a number that cannot be compared to any other number, including itself next week.
REQUIRED_PROVENANCE = (
    "backup_bytes",
    "plaintext_bytes",
    "document_rows",
    "audit_event_rows",
    "engine_version",
    "measured_at",
    # Writes made after the backup was taken. Without them "lost nothing" is what a
    # drill reports when it copies a database nobody wrote to — a result that cannot
    # come out any other way, which is to say not a result.
    "writes_after_backup",
)

# The floor for *claiming* production-like scale — not a measurement and not an SLO.
# Below it, the claim is refused; above it, the claim is merely allowed, and whether
# the corpus is representative remains a question for the corpus owner (§2.6, §2.9).
PRODUCTION_LIKE_MINIMUM_ROWS = 100_000
PRODUCTION_LIKE_MINIMUM_BYTES = 1_000_000_000


@dataclass(frozen=True)
class RecoveryVerdict:
    status: str
    reasons: tuple[str, ...]

    @property
    def executed(self) -> bool:
        return self.status != MISSING

    @property
    def provenance_complete(self) -> bool:
        return self.status not in {MISSING, INCOMPLETE_PROVENANCE}

    @property
    def scale_not_overstated(self) -> bool:
        return self.status != OVERSTATED_SCALE

    @property
    def loss_explained(self) -> bool:
        """Чи вся втрата пояснена вікном, яке навчання створило навмисно."""
        return self.status != UNEXPLAINED_LOSS


def _whole(value: Any) -> int | None:
    """Ціле з поля звіту, або None. Відсутнє поле — не нуль: нуль був би згодою."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _unexplained_loss(report: Mapping[str, Any], provenance: Mapping[str, Any]) -> list[str]:
    """Втрата понад навмисне вікно. Порожній перелік — не за замовчуванням."""
    window = _whole(provenance.get("writes_after_backup"))
    documents = _whole(report.get("lost_documents_total"))
    events = _whole(report.get("lost_events"))
    problems: list[str] = []
    if documents is None:
        problems.append(
            "звіт не називає повної втрати документів (`lost_documents_total`): "
            "величина не виміряна, а невиміряне не є нулем"
        )
    elif window is None:
        problems.append("провенанс не називає вікна записів після бекапу — надлишок не рахується")
    elif documents > window:
        problems.append(
            f"втрачено {documents} документів при вікні {window}: "
            f"{documents - window} понад те, що навчання створило навмисно"
        )
    if events is None:
        problems.append("звіт не називає втрати подій журналу (`lost_events`)")
    elif events > 0:
        problems.append(
            f"втрачено {events} подій журналу аудиту: навчання не створює подій після "
            "бекапу, тож будь-яка їх втрата не пояснена"
        )
    return problems


def classify_recovery(report: Mapping[str, Any] | None) -> RecoveryVerdict:
    """Decide what the drill report supports, without deciding whether it is enough."""

    if not isinstance(report, Mapping) or not report:
        return RecoveryVerdict(MISSING, ("no recovery drill report was produced",))

    reasons: list[str] = []
    provenance = report.get("provenance")
    if not isinstance(provenance, Mapping):
        return RecoveryVerdict(
            INCOMPLETE_PROVENANCE, ("recovery report carries no provenance block",)
        )
    absent = [field for field in REQUIRED_PROVENANCE if provenance.get(field) in (None, "")]
    if absent:
        return RecoveryVerdict(
            INCOMPLETE_PROVENANCE,
            (f"recovery provenance is missing: {', '.join(sorted(absent))}",),
        )

    numeric_problem = recovery_numeric_problem(report, provenance)
    if numeric_problem:
        return RecoveryVerdict(INCOMPLETE_PROVENANCE, (numeric_problem,))

    # ВЕЛИЧИНА втрати, а не лише її форма. Виміряно 04.09.2026 незалежним верифікатором:
    # `lost_events`, `lost_documents` і `lost_documents_total` вимірювались, друкувались і
    # не судились НІКИМ — відновлення, що втратило п'ять тисяч документів, і бездоганне
    # відновлення отримували ОДИН вирок. `recovery_numeric_problem` питає лише, чи число
    # скінченне й невід'ємне; форма без порога є описом, а не умовою.
    #
    # Поріг не «нуль втрат»: навчання НАВМИСНО пише рядки після бекапу й мусить втратити
    # рівно їх — інакше воно нічого не міряє. Отже судиться НАДЛИШОК понад це вікно.
    #
    # RPO лишається несудженим СВІДОМО: жодної оголошеної цілі RPO не існує, і вигадати
    # поріг тут означало б підробити повноваження (§2.9). Несуджене названо, не прибране.
    excess = _unexplained_loss(report, provenance)
    if excess:
        return RecoveryVerdict(UNEXPLAINED_LOSS, tuple(excess))

    declared = str(report.get("scale_class", "")).strip()
    if declared not in {FIXTURE, PRODUCTION_LIKE}:
        return RecoveryVerdict(
            INCOMPLETE_PROVENANCE,
            (f"recovery report declares no recognised scale_class: {declared!r}",),
        )

    if declared == PRODUCTION_LIKE:
        rows, plaintext = recovery_scale_counts(provenance)
        if rows < PRODUCTION_LIKE_MINIMUM_ROWS and plaintext < PRODUCTION_LIKE_MINIMUM_BYTES:
            reasons.append(
                f"report claims {PRODUCTION_LIKE!r} on {rows:.0f} document rows and "
                f"{plaintext:.0f} plaintext bytes, below the floor for that claim "
                f"({PRODUCTION_LIKE_MINIMUM_ROWS} rows or "
                f"{PRODUCTION_LIKE_MINIMUM_BYTES} bytes)"
            )
            return RecoveryVerdict(OVERSTATED_SCALE, tuple(reasons))
        return RecoveryVerdict(MEASURED, ())

    return RecoveryVerdict(
        FIXTURE_SCALE,
        (
            "recovery time measured on a CI fixture; it does not transfer to the "
            "operational corpus (admission ground 2.9)",
        ),
    )
