"""stored search vector: під RLS повнотекстовий індекс недосяжний за побудовою

Revision ID: 0023_evidence_search_vector
Revises: 0022_approval_provenance_boundary

ВИМІРЯНО 04.09.2026 на пілотній базі (31 464 прольоти, PostgreSQL 17):

    добірний запит під межею RLS ........ 3.35 с
    той самий запит без RLS ............. 0.049 с   (GIN, Bitmap Index Scan)
    примусовий послідовний скан із tsvector 0.894 с (3 паралельні робітники)
    той самий скан БЕЗ tsvector ......... 0.085 с

Причина не в плані й не в статистиці — вимкнення `nestloop` нічого не змінило
(3.43 с). Причина в правилі PostgreSQL: умова може стати УМОВОЮ ІНДЕКСУ лише
якщо вона «securely promotable», тобто leakproof або не нижча за рівень
безпекових умов. `ts_match_vq`, `to_tsvector` і `ts_rank_cd` мають
`proleakproof = f`, а RLS додає безпекові умови рівнем нижче. Отже під RLS
повнотекстова умова НЕ МОЖЕ бути умовою індексу — ніколи, ні за яких
статистик. `ix_evidence_spans_search` існував і був недосяжний.

Лишається обчислення `to_tsvector('simple', text)` на КОЖНОМУ рядку: 0.894 −
0.085 ≈ 0.81 с чистого обчислення на 31 тисячі прольотів, і воно росте лінійно
з корпусом. Стовпець прибирає саме це обчислення: вектор рахується РАЗ на
запис і читається як дані.

Розширювальна: старий вираз-індекс лишається, бо ревізія N-1 застосунку
питає `to_tsvector('simple', s.text)` і мусить пережити міграцію. Нічого не
видаляється й не перейменовується.

Стовпець ГЕНЕРОВАНИЙ: тримати його тригером означало б дати запису шанс
розійтися з текстом, а прольоти запечатані — розходження нікому було б
виправляти. `to_tsvector('simple'::regconfig, text)` незмінна (`provolatile
= 'i'`), тож придатна для GENERATED ALWAYS ... STORED — та сама властивість,
на якій тримався й вираз-індекс.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0023_evidence_search_vector"
down_revision: str | None = "0022_approval_provenance_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # `op.add_column`, а не `op.execute("ALTER …")`: гейт розширювальності читає
    # дієслово оператора. `ALTER` він відхиляє за побудовою й правильно — інструмент,
    # яким додають стовпець, тим самим і зносять таблицю. Тут форма несе властивість:
    # стовпець генерований і NULL-придатний, тож наявні рядки не потребують запису.
    op.add_column(
        "evidence_spans",
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
        ),
    )
    op.execute(
        "CREATE INDEX ix_evidence_spans_search_vector "
        "ON evidence_spans USING GIN (search_vector)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_evidence_spans_search_vector")
    op.execute("ALTER TABLE evidence_spans DROP COLUMN IF EXISTS search_vector")
