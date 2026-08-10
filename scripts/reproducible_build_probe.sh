#!/usr/bin/env bash
# Build the image twice from the same tree and say which layers disagree.
#
# OPS-001 asks for a rebuild on an independent runner, a digest comparison, and a record
# of the nondeterminism that remains. The first two are mechanical; the third is the part
# that is usually skipped, and skipping it is how "reproducible" becomes a word in a
# document rather than a property of a build.
#
# What this establishes, and what it does not: two builds on this host, minutes apart,
# from an identical tree. That is the weakest form of the claim — it cannot see a
# dependency that changed between two days, or a builder that differs between two
# machines. It is still the first thing that has to hold, and it did not.
#
# SOURCE_DATE_EPOCH and buildkit's `rewrite-timestamp` normalise the file times buildkit
# controls. What they do not normalise is what a package manager writes inside a layer:
# `apt-get update` fetches an index that changes, and `pip install` records installation
# times in `.dist-info`. Those are named in the report rather than hidden by it.
#
#   make reproducible-build
set -uo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
cd "$root"

dockerfile="${KORPUS_BUILD_DOCKERFILE:-apps/api/Dockerfile}"
out="${KORPUS_BUILD_REPORT:-var/reproducible-build.json}"
mkdir -p "$(dirname "$out")"

# Fixed, so the two builds agree about "now". Taken from the tree rather than the clock:
# a probe whose input changes every second is measuring the clock.
if git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
  epoch="$(git -C "$root" log -1 --pretty=%ct)"
else
  epoch=0
fi
export SOURCE_DATE_EPOCH="$epoch"

build() {
  local tag="$1"
  docker buildx build \
    --file "$dockerfile" \
    --tag "$tag" \
    --no-cache \
    --provenance=false \
    --output "type=docker,rewrite-timestamp=true" \
    --build-arg "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
    . > /dev/null 2>&1
}

layers() {
  docker inspect "$1" --format '{{range .RootFS.Layers}}{{println .}}{{end}}'
}

first=korpus-repro:a
second=korpus-repro:b

build "$first" || { echo "first build failed" >&2; exit 1; }
build "$second" || { echo "second build failed" >&2; exit 1; }

layers "$first" > "$(dirname "$out")/.layers-a"
layers "$second" > "$(dirname "$out")/.layers-b"

python3 - "$out" "$(dirname "$out")/.layers-a" "$(dirname "$out")/.layers-b" \
         "$(docker inspect --format '{{.Id}}' "$first")" \
         "$(docker inspect --format '{{.Id}}' "$second")" \
         "$SOURCE_DATE_EPOCH" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

out, path_a, path_b, id_a, id_b, epoch = sys.argv[1:7]
a = [line for line in Path(path_a).read_text(encoding="utf-8").splitlines() if line]
b = [line for line in Path(path_b).read_text(encoding="utf-8").splitlines() if line]
same = sum(1 for x, y in zip(a, b, strict=False) if x == y)
differing = [
    {"index": index, "first": x[:23], "second": y[:23]}
    for index, (x, y) in enumerate(zip(a, b, strict=False))
    if x != y
]

report = {
    "schema_version": 1,
    "ran_at": datetime.now(UTC).isoformat(),
    "source_date_epoch": int(epoch),
    "image_id_first": id_a,
    "image_id_second": id_b,
    "identical_image": id_a == id_b,
    "layers": len(a),
    "layers_identical": same,
    "layers_differing": differing,
    "known_nondeterminism": [
        "apt-get update fetches an index that changes between runs; the installed "
        "package set is not pinned by version, so two builds can install different "
        "point releases of poppler-utils or tesseract.",
        "pip records installation timestamps in .dist-info even with --no-cache-dir "
        "and pinned hashes; the wheel contents are identical, the metadata is not.",
    ],
    "interpretation": (
        "Two builds on one host, minutes apart, from an identical tree — the weakest "
        "form of the claim, and the first that has to hold. An identical image id means "
        "buildkit's timestamp rewriting covered everything this Dockerfile does; a "
        "differing one means the layers listed above carry something the build does not "
        "control, and the entries under known_nondeterminism are where to look first."
    ),
}
Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
PY

rm -f "$(dirname "$out")/.layers-a" "$(dirname "$out")/.layers-b"
