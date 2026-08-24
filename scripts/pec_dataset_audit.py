"""Dataset validity predicates for PEC evaluation data."""

from __future__ import annotations


def audit_rows(
    rows: list[dict], inventory: set[str] | None
) -> tuple[list[str], set[str], set[str]]:
    issues: list[str] = []
    ids: set[str] = set()
    groups: set[str] = set()
    queries: set[str] = set()
    group_partitions: dict[str, set[str]] = {}
    query_partitions: dict[str, set[str]] = {}
    allowed = {"train", "calibration", "locked_eval"}
    for row in rows:
        rid = str(row.get("id", ""))
        query = str(row.get("query", "")).strip()
        group = str(row.get("group_id", "")).strip()
        partition = str(row.get("partition", ""))
        if not rid or rid in ids:
            issues.append(f"duplicate_or_empty_id:{rid}")
        if not query:
            issues.append(f"empty_query:{rid}")
        if not group:
            issues.append(f"empty_group:{rid}")
        if partition not in allowed:
            issues.append(f"invalid_partition:{rid}:{partition}")
        ids.add(rid)
        groups.add(group)
        queries.add(query)
        group_partitions.setdefault(group, set()).add(partition)
        query_partitions.setdefault(query.casefold(), set()).add(partition)
        if inventory is not None:
            issues.extend(
                f"missing_gold_version:{rid}:{version}"
                for version in row.get("gold_version_ids", [])
                if str(version) not in inventory
            )
    issues.extend(
        f"group_partition_leakage:{group}:{','.join(sorted(partitions))}"
        for group, partitions in sorted(group_partitions.items())
        if len(partitions) > 1
    )
    issues.extend(
        f"exact_query_partition_leakage:{query}:{','.join(sorted(partitions))}"
        for query, partitions in sorted(query_partitions.items())
        if query and len(partitions) > 1
    )
    return issues, groups, queries
