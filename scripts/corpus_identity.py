#!/usr/bin/env python3
"""Чим корпус є ЗАРАЗ — щоб звіт про нього можна було спитати, чи він ще про нього.

`check_answer_axes` перевіряв ВІК звіту: старший за добу — вісь UNMEASURED. Вік це
сурогат. Він відповідає на «коли це міряли», а питання інше: «чи те, що міряли, ще те
саме». Звіт віком 23 години про корпус, який змінився п'ять хвилин тому, проходив; звіт
віком 25 годин про корпус, що не рухався, відхилявся. Обидві помилки — з одного джерела.

Тут рахується ідентичність САМОГО корпусу: кількість документів, версій і прольотів,
сума хешів прольотів і дайджест посилань. Вони рухаються тоді й тільки тоді, коли
рухається те, про що звітують осі корпусу.

**Голови журналу тут НЕМАЄ, і це виправлення власної помилки.** Перша версія її включала —
і живий сервер, який пише подію на кожну відповідь, робив УСІ звіти про корпус несвіжими
за секунди. Осі ставали UNMEASURED від діяльності, якої вони не міряють. Свіжість звіту
мусить залежати від того, ПРО ЩО він, а не від сусіднього. Журнал має власну вісь, і
`measure_audit_integrity` додає голову до своїх входів окремо.

**Чому не sha256 файла бази.** Файл рухається від службових причин, яких вісь не міряє:
`VACUUM`, сторінковий кеш, `ANALYZE`, порядок вставки. Ідентичність мусить бути похідною
від ЗМІСТУ, інакше вона перевимірює нічого й псує свіжі звіти.

**Чому не mtime.** `touch` — не зміна корпусу, а зміна mtime; вимір, який `touch`
обманює, вимірює файлову систему.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def corpus_identity(database: Path) -> dict[str, object]:
    """Стисла, похідна від змісту ідентичність корпусу."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        documents = connection.execute("select count(*) from documents").fetchone()[0]
        versions = connection.execute("select count(*) from document_versions").fetchone()[0]
        spans = connection.execute("select count(*) from evidence_spans").fetchone()[0]
        # Сума хешів прольотів комутативна, тож порядок рядків її не рухає, а зміна
        # бодай одного символу цитати — рухає.
        digest = hashlib.sha256()
        for (text_hash,) in connection.execute(
            "select text_hash from evidence_spans order by text_hash"
        ):
            digest.update(str(text_hash).encode("ascii"))
        # Посилання не входять у text_hash, а вісь простежуваності міряє саме їх.
        uris = hashlib.sha256()
        for (uri,) in connection.execute(
            "select coalesce(source_uri, '') from document_versions order by id"
        ):
            uris.update(str(uri).encode("utf-8"))
    finally:
        connection.close()
    return {
        "documents": int(documents),
        "versions": int(versions),
        "spans": int(spans),
        "span_text_digest": digest.hexdigest(),
        "source_uri_digest": uris.hexdigest(),
    }


def identity_digest(identity: dict[str, object]) -> str:
    """Один рядок, який можна порівняти, не читаючи шість полів."""
    parts = "|".join(f"{key}={identity[key]}" for key in sorted(identity))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def report_inputs(database: Path, measurer: Path, **extra: object) -> dict[str, object]:
    """Усе, від чого залежить звіт — щоб гейт міг спитати «це ще про той самий стан».

    Вимірювач входить сюди нарівні з даними. Звіт застаріває не лише коли рухається
    корпус, а й коли міняється те, ЧИМ його міряли: інакше правка визначення проби
    лишала б у силі число, порахованее старим визначенням, і воно виглядало б свіжим.
    """
    identity = corpus_identity(database)
    return {
        "corpus": identity_digest(identity),
        "corpus_shape": identity,
        "measurer": hashlib.sha256(measurer.read_bytes()).hexdigest(),
        **extra,
    }


def inputs_digest(inputs: dict[str, object]) -> str:
    """Один рядок для порівняння. `corpus_shape` виключено — це пояснення, не вхід."""
    parts = "|".join(f"{key}={inputs[key]}" for key in sorted(inputs) if key != "corpus_shape")
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()
