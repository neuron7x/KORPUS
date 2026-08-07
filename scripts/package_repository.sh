#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
version="${KORPUS_RELEASE_VERSION:-v5.0.0}"
name="KORPUS_FINAL_ASSURANCE_${version}"
mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

# The source tree is exactly the committed revision; generated evidence is copied explicitly.
git archive --format=tar HEAD | tar -xf - -C "$tmp"
if [[ -d reports ]]; then
  rm -rf "$tmp/reports"
  cp -a reports "$tmp/reports"
fi
for artifact in source-sbom.cdx.json api-sbom.cdx.json web-sbom.cdx.json; do
  [[ -f "$artifact" ]] && cp "$artifact" "$tmp/$artifact"
done
find "$tmp" -type f -path '*/infra/secrets/*.txt' -delete

# The sealed evidence registry and the frozen corpus release travel with the source.
# Without them the package is a system nobody can check: the reports that show what it
# does under load, when a dependency is broken, and against its own corpus all live in
# `var/`, which is cleaned, and in CI artefacts, which expire in weeks.
if [[ -d var/evidence ]]; then
  mkdir -p "$tmp/evidence"
  cp -a var/evidence/. "$tmp/evidence/"
fi
if [[ -d var/releases ]]; then
  mkdir -p "$tmp/evidence/releases"
  cp -a var/releases/. "$tmp/evidence/releases/"
fi

# Named explicitly rather than left for a reader to discover by its absence.
cat > "$tmp/WHAT_IS_IN_THIS_PACKAGE.md" <<'DOC'
# Що в цьому пакеті

Джерело на зафіксованій ревізії, звіти гейтів, і запечатаний реєстр доказів. Усе, що
можна перевірити, не маючи цієї машини.

## Є

- `apps/`, `scripts/`, `config/`, `deploy/`, `evals/`, `docs/` — система і її гейти
- `reports/` — звіти релізу: тести, покриття, мутація, міграція, масштаб, операційний
- `evidence/registry.json` — реєстр доказів під їхніми дайджестами, запечатаний
- `evidence/objects/` — самі звіти: навантаження, хаос, еталонний набір, сканери
- `evidence/releases/` — підписаний маніфест корпусу: які версії могли бути процитовані
- `REPOSITORY_MANIFEST.json` — дайджест кожного файлу

## Немає, і чому

- **Секрети.** `infra/secrets/*.txt` видалено при пакуванні. `scripts/init_local_secrets.sh`
  згенерує нові.
- **Корпус.** 1648 документів, 118 622 фрагменти, ~2 ГБ. Це дані з Google Drive, а не
  система. Відтворюються включеними скриптами:

      make drive-public FOLDER_ID=<id> INTO=var/corpus/ml MAX_FILE_BYTES=2000000
      make draft-manifest ROOT=var/corpus/ml OUT=var/corpus/ml-manifest.json FROM_SNAPSHOT=1
      make import-corpus MANIFEST=var/corpus/ml-manifest.json IMPORT_FLAGS="--root var/corpus/ml"

  Або з шифрованої резервної копії: `make restore-sqlite BACKUP=<файл> INTO=var/restored`.
- **Дозвіл на продакшн.** `production_authorized` = false. Це не помилка пакування: підпис
  власника ризику — рішення людини, і жоден код тут не може його видати.

## Що доведено, а що ні

`reports/RESEARCH_ASSURANCE_REPORT.json` несе дайджест дерева, з якого зібрано кожен
звіт. Якщо він не збігається з деревом — докази про інше дерево.

Дев'ять пунктів реєстру аудиту лишаються EXTERNAL_DEBT: підпис власника ризику,
незалежний pentest, людська розмітка еталону, чергування, HA-кластер, TLS-сертифікат,
KMS/HSM, налаштування GitLab, юридичний висновок про права. Жоден не закривається кодом
у цьому дереві, і кожен названий у `docs/audit/closure/`.
DOC
python3 "$root/scripts/generate_manifest.py" "$tmp"
cp "$tmp/REPOSITORY_MANIFEST.json" "$root/REPOSITORY_MANIFEST.json"
(
  cd "$tmp"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 touch -h -d '@0'
  LC_ALL=C find . -type f -print | LC_ALL=C sort | zip -X -q "$root/dist/${name}.zip" -@
)
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
cat "dist/${name}.zip.sha256"
