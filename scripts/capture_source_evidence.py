#!/usr/bin/env python3
"""Read every catalogued source once, and record what was actually read.

Measured 2026-08-29 on 168 sources: 128 carried no content_probe, no integrity_anchor and
no attachment_anchors. The catalogue named them, gave each a provenance tier and a rights
status, and had never opened one. `content_signal` and `remote_digest` do not close that —
robots.txt and an ETag describe the *server*, not the document. A bibliography that has
never been read is a bibliography, and a soldier asking what he is entitled to cannot be
answered out of one.

`probe_source_content.py` cannot do this: its card-versus-/print measurement is specific to
zakon.rada.gov.ua, and 96 of the ungrounded ingestible sources are on 37 other hosts.

What lands in the tree is an extract record, not the document. The extracted text of the 96
runs to tens of megabytes — ARM-ATP-3-21-11-2020 alone is 30.9 MB of PDF and 1.10 MB of
text — and config/ is not a corpus. The record carries what makes the claim falsifiable:

    remote_sha256      the bytes that were served, so a rewrite upstream is visible
    full_text_sha256   what this system's extractor made of them, so a change in either
                       the bytes or the extractor is visible
    pages / words      the shape of the document, so a 404 cannot pass as an annex
    a bounded body     the opening and closing words, so a human can see it is the right
                       document and `_content_problem`'s 120-word floor measures something

Refusals are recorded as refusals. ORG-MECH-STATUTE-P3 is 20.4 MB of PDF the extractor
rejects outright — "PDF page count exceeds configured limit" — and that is a fact about a
source the catalogue calls ingestible, not a gap to leave blank. `evidence_refusal` names
it with the extractor's own words. UNKNOWN does not become PASS by being written down.

Two things it will not do. It will not capture where the site reserved its content against
us: `content_signal.verdict == "reserved_against_us"` is a decision already measured, and
overriding it here would launder it. And it will not overwrite an existing anchor without
`--refresh`, so a re-run cannot quietly replace evidence with a fresh 404.

    capture_source_evidence.py --selftest        # prove each refusal fires
    capture_source_evidence.py --limit 5         # a sample, no writes
    capture_source_evidence.py --write
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
import zlib
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

# Не друге визначення «прочитаного». Гейт уже вирішує, що рахується доказом, і сьогодні
# це рішення змінилось: `document_probe` увійшов у набір, `remote_digest` навмисно ні.
# Власна копія цієї арифметики розійшлася б із гейтом тихо — рівно те, що коштувало
# сьогодні нестабільного BOUND, коли `source_tree_digest` мав друге визначення джерела.
from catalog_merge import by_id, merge_write, vanished_problem  # noqa: E402
from validate_doctrine_catalog import has_evidence  # noqa: E402

CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
CAPTURES = ROOT / "config/corpus/captures"
#: Chrome's. A default urllib agent is refused by several of these hosts with 403, and a
#: 403 recorded as "unreachable" would be a fact about the client, not about the source.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
#: Words kept from each end. 400 + 200 clears the gate's 120-word floor with room, and is
#: enough for a reader to recognise the document without the record becoming the document.
HEAD_WORDS = 400
TAIL_WORDS = 200
#: Below this the extraction did not produce a document, whatever the HTTP status said.
#:
#: НЕ ПЕРЕВІРЕНИЙ ДАНИМИ, і це виміряно, а не припущено. Станом на 2026-08-30: 92 захоплені
#: документи, найтонший 391 слово, розрив до порога 1.96×, і **жодної відмови класу
#: `too_few_words` у каталозі — поріг не спрацював жодного разу**. Він стоїть у розумному
#: місці за міркуванням (404-сторінка дає десятки слів), але міркування — це не вимір.
#:
#: Гірше: контрприклад, який його перевіряв би, зник через ПРАВИЛЬНУ дію. Сторінки-перепони
#: (Cloudflare, 403) тепер відсіюються раніше й записуються як `evidence_refusal`, тож усе,
#: що було нижче 200 слів, більше сюди не доходить. Виправлення однієї вади знищило доказ
#: правильності іншої, і жодне з двох рішень не є помилкою — помилкою було б не помітити.
#: `make threshold-distance` каже це вголос замість мовчати.
MIN_WORDS = 200
MEDIA_SUFFIX = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}
BLOCKED_VERDICT = "reserved_against_us"
TAG = re.compile(r"<[^>]+>")

#: Дві різні речі вимірюються, і жодна з них не називається просто «sha256».
#: Це третій випадок за день, коли в одному записі живуть різні виміри під схожими
#: іменами; перші два коштували вироку STALE про дерево, яке не зсувалось. Область
#: несе саме поле, а не суфікс, який читач мусив би розрізнити.
BYTES_SCOPE = "bytes_as_served"
TEXT_SCOPE = "text_as_extracted"


#: Класи відмов. Текстова причина не переживає місяця: через місяць ніхто не згадає,
#: які з дев'яти недосяжних варто перепробувати. 403 від фільтра — не те саме, що 404
#: від зниклого джерела, і рішення «пробувати ще» приймається за класом, не за прозою.
RETRYABLE = frozenset({"http_forbidden", "transport_reset", "transport_timeout"})
#: Класи, які МОЖУТЬ виявитись питанням точки доступу, а не джерела. `dns_unresolved`
#: свідомо поза списком: ім'я, якого немає в DNS, не з'явиться від іншого підключення —
#: це джерело, яке зникло. `tls_refused` теж: сертифікат не залежить від того, звідки ми
#: дивимось.
VANTAGE_CANDIDATES = frozenset({"transport_reset", "transport_timeout", "transport_error"})


class Capture(dict[str, Any]):
    """The record written next to a source. A dict subclass so json.dump needs no encoder."""


def record_refusal(identifier: str, reason: str, kind: str, **extra: Any) -> Capture:
    """The single place a refusal is built, so every refusal is written down the same way.

    Every caller of this is a broad `except`. A broad handler that returns a value the
    caller cannot distinguish from success is the shape this repository has found in its
    gates, its reports and its aggregator; the refusal built here is carried out to
    `evidence_refusal` in the catalogue, with its class and its date, which is a more
    durable record than a log line nobody reads.
    """
    return Capture(id=identifier, refusal=reason, refusal_class=kind, **extra)


def _decode(payload: bytes, encoding: str) -> bytes:
    """Undo Content-Encoding before hashing.

    Found on the first run: armyinform.com.ua serves gzip regardless of Accept-Encoding,
    urllib does not decode it, and the extractor reported "HTML content detected as
    application/gzip" — a real page recorded as an unreadable format. Hashing the
    compressed bytes would also have made the digest depend on the server's compression
    level rather than on the document.
    """
    if encoding == "gzip":
        return gzip.decompress(payload)
    if encoding in {"deflate", "zlib"}:
        return zlib.decompress(payload, -zlib.MAX_WBITS)
    return payload


def canonical(text: str) -> str:
    """Те, що хешується, — документ, а не його транспортне оформлення.

    Метаморфна проба (той самий документ, інше кодування рядків) показала, що без цього
    `\r\n` проти `\n` дає інший digest — тобто «документ змінився» про документ, який
    не змінювався. NFC із тієї ж причини: одна українська літера у двох формах Unicode
    друкується однаково й хешується по-різному.
    """
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def encode_uri(uri: str) -> str:
    """Відсоткове кодування шляху й запиту: urllib не вміє не-ASCII в URL.

    Дві постанови КМУ мають кирилицю в шляху, і прогін відмовив їх із
    `UnicodeEncodeError: 'ascii' codec can't encode character '\u043f'`. Записалось як
    `transport_error` — тобто **наша вада пішла в каталог як факт про джерело**, рівно та
    підміна, від якої відділені класи відмов. Кодування — наш бік, і робиться тут.
    """
    parts = urlsplit(uri)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii")
            if parts.netloc.isascii() is False
            else parts.netloc,
            quote(parts.path, safe="/%"),
            quote(parts.query, safe="=&%"),
            parts.fragment,
        )
    )


def fetch(uri: str, timeout: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        encode_uri(uri), headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        media = str(response.headers.get("Content-Type", "")).split(";")[0].strip()
        return _decode(raw, str(response.headers.get("Content-Encoding", "")).lower()), media


def extract(path: Path, media: str) -> tuple[list[str], str]:
    """The system's own extractor, so a refusal here is the refusal ingestion would give."""
    from korpus.infrastructure.extraction import extract_pages_from_path

    pages, mode = extract_pages_from_path(
        path, path.name, media or "text/html", ocr_enabled=False, ocr_languages="ukr"
    )
    return [page.text for page in pages], str(mode)


def _header_lines(meta: dict[str, Any], prefix: str = "") -> list[str]:
    """Flatten the two scopes into `scope.field:` lines so the record stays readable text.

    Written out rather than repr'd: a nested dict printed into the record would make the
    anchored file's own digest depend on Python's dict formatting.
    """
    lines: list[str] = []
    for key, value in meta.items():
        if isinstance(value, dict):
            lines.extend(_header_lines(value, f"{prefix}{key}."))
        else:
            lines.append(f"{prefix}{key}: {value}")
    return lines


def render(source: dict[str, Any], meta: dict[str, Any], text: str) -> str:
    """The extract record. Bounded body, both digests, and a line saying it is bounded."""
    words = text.split()
    body = (
        " ".join(words)
        if len(words) <= HEAD_WORDS + TAIL_WORDS
        else " ".join(words[:HEAD_WORDS]) + "\n\n[…]\n\n" + " ".join(words[-TAIL_WORDS:])
    )
    header = "\n".join(_header_lines(meta))
    return (
        f"# KORPUS extract record — {source['id']}\n"
        f"# {source['canonical_title']}\n"
        f"#\n"
        f"# This is not the document. It is a record of having read it: the digests below\n"
        f"# bind both the bytes served and the text this system extracted from them, and\n"
        f"# the body is the opening and closing words only.\n"
        f"{header}\n"
        f"---\n"
        f"{body}\n"
    )


def _needs_evidence(source: dict[str, Any], refresh: bool, unread: bool = False) -> bool:
    """ВИМІРЯНО і ПРОЧИТАНО — різні предмети, і сплутати їх коштувало корпусу.

    `has_evidence` — предикат ГЕЙТА: чи про джерело щось виміряно. `document_probe`
    рахується там законно (сторінки, слова, `text_sha256`), але від виміру документ
    прочитаним не стає. 2026-08-30: 73 зі 165 придатних джерел мали доказ і НЕ мали
    запису прочитання — серед них усі чотири ключові документи розділу «Противник»,
    включно з ATP 7-100.1 про тактику РФ. Прогін захоплення пропускав їх мовчки, бо питав
    гейтівським предикатом, а якість пошуку мірялася на корпусі, де їх немає.
    """
    if not source.get("ingestible"):
        return False
    if refresh:
        return True
    if unread:
        return not (CAPTURES / f"{source['id']}.txt").is_file()
    return not has_evidence(source)


def _blocked(source: dict[str, Any]) -> str | None:
    signal = source.get("content_signal")
    if isinstance(signal, dict) and signal.get("verdict") == BLOCKED_VERDICT:
        return (
            "content_signal.verdict is reserved_against_us — the site reserved its content "
            "against systems like this one, and capturing here would launder that decision"
        )
    return None


#: Екстрактор відмовляє з двох різних причин, і вони вимагають різних дій. Наш ліміт
#: знімається зміною НАШИХ налаштувань; підміна типу вмісту — ні. Той самий клас на обидва
#: означав би, що «підняти ліміт» і «сервер віддає JS під HTML-URL» лежать в одній купі.
CONTENT_MISMATCH_MARKERS = ("detected as", "is not a", "claims")
#: Скільки початкових байтів дивитись, шукаючи розмітку. Досить, щоб обійти BOM, коментар
#: і `<meta>`, і замало, щоб зустріти вбудований скрипт як «початок документа».
HTML_HEAD_BYTES = 1024
HTML_OPENERS = (b"<!doctype html", b"<html")


def _looks_like_html(payload: bytes) -> bool:
    """Чи це справді HTML — за розміткою, не за нюхом класифікатора.

    Виміряно 2026-08-30 паралельною сесією: обидві сторінки, які наш екстрактор відхилив
    як «HTML content detected as application/javascript», віддають HTTP 200, text/html і
    13 633 та 2 321 слово справжнього тексту. `file` каже про них «JavaScript source, with
    very long lines» — нюхача збиває довгий рядок вбудованого скрипту, а в ICDS цей скрипт
    стоїть найпершим у `<head>`. Це властивість класифікатора, а не сторінки, і повірити
    йому означало б викинути офіційну позицію НАТО щодо РФ через евристику.
    """
    # BOM знімається ДО lstrip: `lstrip()` бачить \xef\xbb\xbf як звичайні байти, і той
    # самий документ, збережений із BOM, читався б як не-HTML. Проба на це в selftest.
    head = payload[:HTML_HEAD_BYTES].removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    return any(head.startswith(opener) for opener in HTML_OPENERS) and b"</body>" in payload.lower()


def _extractor_class(message: str, payload: bytes = b"") -> str:
    """Чий це бік. Три стани, бо їх справді три.

    `extractor_refused` — наш ліміт (сторінок, розміру): знімається нашими налаштуваннями.
    `content_type_mismatch` — сервер справді віддав не те: наші налаштування не поможуть.
    `extractor_misclassified` — наш класифікатор ПОМИЛИВСЯ: вміст саме той, що обіцяно, і
    відмова належить нам, а не джерелу. Без третього стану дефект нюхача записувався б у
    провину сторінці, і хибне «джерело погане» пережило б причину, яка його породила.
    """
    lowered = message.lower()
    if not any(marker in lowered for marker in CONTENT_MISMATCH_MARKERS):
        return "extractor_refused"
    return "extractor_misclassified" if _looks_like_html(payload) else "content_type_mismatch"


def _host_answers(uri: str, timeout: int) -> bool | None:
    """Чи відповідає КОРІНЬ хоста — байдуже яким статусом. `None`, якщо uri не розібрати.

    Будь-який HTTP-код означає «так»: 403 і 404 приходять від сервера, тобто ми до нього
    дістались. Лише транспортна невдача на корені означає, що хоста немає ЗВІДСИ.
    """
    parts = urlsplit(uri)
    if not parts.scheme or not parts.hostname:
        return None
    request = urllib.request.Request(
        f"{parts.scheme}://{parts.netloc}/", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001 — одна річ: звідси хоста не видно
        return False


def _transport_class(error: BaseException, uri: str = "", timeout: int = 30) -> str:
    """A reset is a filter; a timeout may be a route; a DNS failure is a source that is gone.

    Nine sources were unreachable on 2026-08-29 and the difference decides which of them is
    worth trying again. Folded into one string, that decision is lost by next month.

    Четверта категорія, названа паралельною сесією 2026-08-30 і виміряна нею на родині
    хостів TRADOC: `host_unreachable_from_here`. `oe.t2com`, `rdl.train`, `odin.tradoc`
    дають HTTP 000 з ЦІЄЇ машини, тоді як `jts.health.mil` і `armypubs.army.mil` з неї ж
    відповідають 200. Повтор цього не змінить ніколи — а інша точка доступу змінить.
    Плутати це з «бік джерела» означає списати живий документ як недоступний назавжди;
    плутати з «наш ліміт» означає марно крутити налаштування.
    Вимір, а не здогад: питаємо КОРІНЬ хоста. Транспортна невдача й на ньому — хоста не
    видно звідси; будь-який HTTP-код від кореня означає, що ми дістались, і тоді причина
    в шляху, а не в точці доступу.
    """
    text = str(error).lower()
    fine = "transport_error"
    if "reset by peer" in text or "connection refused" in text:
        fine = "transport_reset"
    elif "timed out" in text or "timeout" in text:
        fine = "transport_timeout"
    elif "name or service not known" in text or "nodename nor servname" in text:
        fine = "dns_unresolved"
    elif "certificate" in text or "ssl" in text:
        fine = "tls_refused"
    if uri and fine in VANTAGE_CANDIDATES and _host_answers(uri, timeout) is False:
        return "host_unreachable_from_here"
    return fine


def _cached(staging: Path, identifier: str) -> tuple[bytes, str] | None:
    """Bytes already fetched in an earlier run of this same tool, if any.

    Re-deriving a record must not mean re-downloading 589 MB. It also makes the derivation
    step falsifiable on its own: the same bytes must produce the same text digest, so a
    change in the record with `--from-cache` is a change in the extractor, never in the
    network.
    """
    for path in sorted(staging.glob(f"{identifier}.*")):
        media = next((m for m, s in MEDIA_SUFFIX.items() if s == path.suffix), "text/html")
        return path.read_bytes(), media
    return None


def _obtain(
    source: dict[str, Any], timeout: int, staging: Path, from_cache: bool
) -> tuple[bytes, str] | Capture:
    """The bytes, or the refusal that stands in their place. Never neither, never both."""
    identifier = str(source["id"])
    uri = str(source.get("source_uri", "")).strip()
    if not uri:
        return record_refusal(identifier, "no source_uri to read", "no_uri")
    reserved = _blocked(source)
    if reserved:
        return record_refusal(identifier, reserved, "rights_reserved")
    cached = _cached(staging, identifier) if from_cache else None
    if cached is not None:
        return cached
    try:
        return fetch(uri, timeout)
    except urllib.error.HTTPError as error:
        return record_refusal(
            identifier,
            f"HTTP {error.code} from {uri}",
            "http_forbidden" if error.code in (401, 403) else "http_error",
            http_status=error.code,
        )
    except Exception as error:  # noqa: BLE001 — every transport failure is one fact: unread
        return record_refusal(
            identifier,
            f"{type(error).__name__}: {str(error)[:160]}",
            _transport_class(error, uri, timeout),
        )


#: Витягнутий текст, збережений ПОЗА каталогом і ключований байтами, з яких він постав.
#: Ратчет, який відмовляє у записі, не сміє коштувати роботи: 92 документи — це 11 743
#: сторінки екстракції, і поки вимір жив лише всередині каталогу, кожен відкіт платив за
#: них знову. Названо паралельною сесією 2026-08-30, яка втратила так 81 вимір: «вимір —
#: це факт, знятий тоді-то; він не має жити в одному місці з файлом, який редагують троє».
#: Ключ — sha256 самих байтів, а не id: тоді запис, відновлений із кешу, доведено походить
#: рівно з того вмісту, а не з того самого імені.
#: ПОЗА деревом. Перша версія клала кеш у `var/evidence-capture/derived/` — тобто в
#: єдиний каталог, призначення якого бути видаленим: `make clean` робить `rm -rf var`.
#: 2026-08-30 о 07:58 він так і зник разом із 530 МБ вихідних байтів і корпусною базою.
#: Правило «вимір не має жити в одному місці з файлом, який редагують троє» я почув і
#: застосував наполовину; повне звучить так: **вимір не має жити там, де його зносить
#: рутинна операція**. `var/` існує рівно для того, щоб його зносили.
DERIVED = Path.home() / ".korpus-cache/derived-text"


def _derived_path(staging: Path, payload: bytes) -> Path:
    return DERIVED / f"{hashlib.sha256(payload).hexdigest()}.json"


def _remember(staging: Path, payload: bytes, result: Capture) -> None:
    target = _derived_path(staging, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"meta": result["meta"], "text": result["text"]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _recall(staging: Path, payload: bytes, identifier: str) -> Capture | None:
    target = _derived_path(staging, payload)
    if not target.is_file():
        return None
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Пошкоджений кеш — не привід узяти з нього щось: перечитуємо з байтів.
        return None
    if not isinstance(stored.get("meta"), dict) or not isinstance(stored.get("text"), str):
        return None
    return Capture(id=identifier, text=stored["text"], meta=stored["meta"])


def capture_one(
    source: dict[str, Any], timeout: int, staging: Path, from_cache: bool = False
) -> Capture:
    """Fetch, extract, and return either an anchor or a named refusal. Never neither."""
    identifier = str(source["id"])
    uri = str(source.get("source_uri", "")).strip()
    obtained = _obtain(source, timeout, staging, from_cache)
    if isinstance(obtained, Capture):
        return obtained
    payload, media = obtained
    remembered = _recall(staging, payload, identifier) if from_cache else None
    if remembered is not None:
        return remembered

    suffix = MEDIA_SUFFIX.get(media, ".html")
    staging.mkdir(parents=True, exist_ok=True)
    scratch = staging / f"{identifier}{suffix}"
    scratch.write_bytes(payload)
    try:
        pages, mode = extract(scratch, media)
    except Exception as error:  # noqa: BLE001 — the extractor's refusal is the finding
        return record_refusal(
            identifier,
            f"extractor refused: {str(error)[:160]}",
            _extractor_class(str(error), payload),
            remote_bytes=len(payload),
            media_type=media,
        )
    text = canonical("\n".join(pages))
    words = len(text.split())
    if words < MIN_WORDS:
        return record_refusal(
            identifier,
            f"only {words} words extracted from {len(payload)} bytes — "
            f"an error page or a stub, not a document (floor {MIN_WORDS})",
            "too_few_words",
            remote_bytes=len(payload),
            media_type=media,
        )
    result = Capture(
        id=identifier,
        text=text,
        meta={
            "uri": uri,
            "fetched_on": date.today().isoformat(),
            "media_type": media,
            BYTES_SCOPE: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "means": "точні байти, які віддав сервер, після зняття Content-Encoding",
            },
            TEXT_SCOPE: {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "extractor": mode,
                "pages": len(pages),
                "words": words,
                "canonicalised": "CRLF→LF, NFC",
                "means": "що з тих байтів зробив екстрактор ЦІЄЇ системи",
            },
            "body_is_bounded": f"first {HEAD_WORDS} and last {TAIL_WORDS} words",
        },
    )
    _remember(staging, payload, result)
    return result


def commit(
    updates: dict[str, Capture],
    refusals: dict[str, dict[str, object]],
    catalog_path: Path | None = None,
) -> list[str]:
    """Apply this run's findings to the catalogue as it is on disk right now.

    The merge discipline lives in `catalog_merge`, shared with the recheck tool: a second
    implementation of "how to write the catalogue" is how the two would drift, and the
    drift would stay invisible until something was lost.
    """

    def apply(catalog: dict[str, Any]) -> list[str]:
        before = ungrounded(catalog)
        was = json.dumps(catalog, sort_keys=True, ensure_ascii=False)
        sources = by_id(catalog)
        problems = vanished_problem(set(updates) | set(refusals), set(sources))
        for identifier, result in updates.items():
            if identifier in sources:
                _write(sources[identifier], result)
        for identifier, refusal in refusals.items():
            if identifier in sources:
                sources[identifier]["evidence_refusal"] = refusal
        changed = json.dumps(catalog, sort_keys=True, ensure_ascii=False) != was
        return problems + ratchet(catalog, before, changed)

    return merge_write(catalog_path or CATALOG, apply)


def _write(source: dict[str, Any], result: Capture) -> None:
    CAPTURES.mkdir(parents=True, exist_ok=True)
    target = CAPTURES / f"{result['id']}.txt"
    target.write_text(render(source, result["meta"], result["text"]), encoding="utf-8")
    source["integrity_anchor"] = {
        "path": str(target.relative_to(ROOT)),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "captured_on": result["meta"]["fetched_on"],
    }
    source["capture"] = result["meta"]
    source.pop("evidence_refusal", None)


PROBES: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "джерело без source_uri",
        {"id": "P1", "ingestible": True, "source_uri": "  "},
        "no source_uri",
    ),
    (
        "сайт зарезервував вміст проти нас",
        {
            "id": "P2",
            "ingestible": True,
            "source_uri": "https://example.invalid/x",
            "content_signal": {"verdict": BLOCKED_VERDICT},
        },
        "reserved_against_us",
    ),
    (
        "хост не існує",
        {"id": "P3", "ingestible": True, "source_uri": "https://nx.invalid./x"},
        "Error",
    ),
)


def selftest() -> int:
    """Кожна відмова показана такою, що спрацьовує, і кожен поріг — таким, що ріже."""
    bad = 0
    for name, entry, expected in PROBES:
        got = str(capture_one(entry, 5, ROOT / "var/selftest-capture").get("refusal", ""))
        if expected not in got:
            bad += 1
            print(f"  ✗ {name}: очікували {expected!r}, отримали {got!r}")
    # Поріг слів ріже: 199 слів — відмова, 200 — ні. Перевіряється на самому предикаті,
    # бо мережу в selftest не викликаємо.
    # Клас відмови екстрактора: наш ліміт проти підміни типу вмісту.
    html = (
        "<!DOCTYPE html>\n<html><head><script>x=1</script></head><body>текст</body></html>".encode()
    )
    js = b"(function(){var x=1;})();\n" * 40
    for message, payload, expected in (
        ("HTML content detected as application/javascript", html, "extractor_misclassified"),
        ("HTML content detected as application/javascript", js, "content_type_mismatch"),
        ("PDF page count exceeds configured limit", b"%PDF-1.7", "extractor_refused"),
        ("encrypted PDF requires a password", b"%PDF-1.7", "extractor_refused"),
        # Розмітка з BOM і провідними пробілами — той самий документ, інакше записаний.
        (
            "HTML content detected as application/javascript",
            b"\xef\xbb\xbf  " + html,
            "extractor_misclassified",
        ),
        # …але обрізаний HTML без </body> не вважається доведеним HTML.
        (
            "HTML content detected as application/javascript",
            b"<!DOCTYPE html><html>",
            "content_type_mismatch",
        ),
    ):
        got = _extractor_class(message, payload)
        if got != expected:
            bad += 1
            print(f"  ✗ {message[:34]} / {payload[:12]!r}: очікували {expected}, отримали {got}")
    for count, must_refuse in ((MIN_WORDS - 1, True), (MIN_WORDS, False)):
        if (count < MIN_WORDS) is not must_refuse:
            bad += 1
            print(f"  ✗ поріг слів не ріже на {count}")
    # Обмежене тіло справді обмежене, і воно все ще проходить 120-словну підлогу гейта.
    long_text = " ".join(f"w{n}" for n in range(5000))
    rendered = render({"id": "P4", "canonical_title": "проба"}, {"words": 5000}, long_text)
    kept = len(TAG.sub(" ", rendered).split())
    if kept >= 5000:
        bad += 1
        print(f"  ✗ тіло не обмежене: {kept} слів")
    if kept < 120:
        bad += 1
        print(f"  ✗ обмежене тіло не проходить підлогу гейта: {kept} слів")
    # Content-Encoding знімається перед хешуванням: інакше digest залежить від рівня
    # стиснення сервера, а не від документа.
    if _decode(gzip.compress(b"x" * 100), "gzip") != b"x" * 100:
        bad += 1
        print("  ✗ gzip не розпаковується")
    bad += _metamorphic()
    bad += _ratchet_probes()
    bad += _concurrency_probe()
    bad += _derived_cache_probe()
    bad += _uri_encoding_probe()
    bad += _vantage_probe()
    total = len(PROBES) + 11 + len(EQUIVALENT) + len(RATCHET_PROBES) + 16 + len(URI_CASES)
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


#: Метаморфні проби: той самий документ, записаний інакше. Кожна, що змінює
#: text_as_extracted.sha256, — місце, де digest залежить від транспорту, а не від
#: документа. Отрути цього не показують: кожна перевіряє один вхід, а тут стверджується
#: відношення між двома. Ціна асиметрична — відмова приходить у вигляді факту («STALE»,
#: «документ змінився»), і факт ніхто не переміряє.
EQUIVALENT: tuple[tuple[str, str, str], ...] = (
    ("той самий текст із CRLF", "рядок один\nрядок два\n", "рядок один\r\nрядок два\r\n"),
    ("той самий текст із самим CR", "рядок один\nрядок два\n", "рядок один\rрядок два\r"),
    (
        "та сама літера в іншій формі Unicode",
        "\u0439\u043e\u0433\u043e",
        "\u0438\u0306\u043e\u0433\u043e",
    ),
)


def _metamorphic() -> int:
    bad = 0
    for name, one, other in EQUIVALENT:
        if canonical(one) != canonical(other):
            bad += 1
            print(f"  ✗ ХИБНЕ ВІДХИЛЕННЯ: {name} — той самий документ дав інший digest")
    # І зворотний бік: канонізація не сміє злити РІЗНІ документи в один хеш.
    if canonical("рядок один") == canonical("рядок два"):
        bad += 1
        print("  ✗ канонізація стирає різницю між різними документами")
    return bad


#: Ратчет мусить відхиляти рівно три речі: зростання, стелю не-число, і прогін, який
#: нічого не змінив, але записує себе як успіх.
RATCHET_PROBES: tuple[tuple[str, tuple[int, int], dict[str, Any], str], ...] = (
    ("стеля не є цілим числом", (5, 5), {"sources_without_evidence": "багато"}, "не є цілим"),
    ("прогін нічого не змінив", (2, 1), {}, "не змінив у каталозі нічого"),
    (
        "непрочитаних більше, ніж дозволяє записана стеля",
        (9, 9),
        {"sources_without_evidence": 1, "ingestible_without_evidence": 1},
        "вище записаної стелі",
    ),
    ("непрочитаних побільшало проти початку прогону", (0, 0), {}, "зросла 0 → 2"),
)


def _ratchet_probes() -> int:
    bad = 0
    for name, before, ceiling, expected in RATCHET_PROBES:
        catalog: dict[str, Any] = {
            "sources": [{"id": "A", "ingestible": True}, {"id": "B", "ingestible": False}],
            "evidence_ceiling": {
                "sources_without_evidence": 99,
                "ingestible_without_evidence": 99,
                **ceiling,
            },
        }
        found = " ".join(ratchet(catalog, before, changed=name != "прогін нічого не змінив"))
        if expected not in found:
            bad += 1
            print(f"  ✗ {name}: очікували {expected!r}, отримали {found!r}")
    return bad


def ungrounded(catalog: dict[str, Any]) -> tuple[int, int]:
    """Скільки джерел досі не прочитано. Та сама арифметика, що в rule-гейті."""
    sources = [s for s in catalog["sources"] if isinstance(s, dict)]
    without = [s for s in sources if not has_evidence(s)]
    return len(without), len([s for s in without if s.get("ingestible")])


def ratchet(catalog: dict[str, Any], before: tuple[int, int], changed: bool = True) -> list[str]:
    """Відмовити, якщо стеля не впала.

    Намір «стеля мусить впасти, інакше захоплення нічого не змінило» не переживає
    наступного коміту, поки він намір. Це та сама позиція, що `evidence_floor` до
    ратчета: число, яке хтось мав би перевірити руками. Тому прогін сам себе відхиляє.
    """
    after = ungrounded(catalog)
    ceiling = catalog.get("evidence_ceiling")
    if not isinstance(ceiling, dict):
        return ["evidence_ceiling відсутня або не є об'єктом — нема чого опускати"]
    problems = []
    for index, key in enumerate(("sources_without_evidence", "ingestible_without_evidence")):
        if after[index] > before[index]:
            problems.append(f"{key} зросла {before[index]} → {after[index]}")
        recorded = ceiling.get(key)
        if not isinstance(recorded, int) or isinstance(recorded, bool):
            problems.append(f"{key} у стелі не є цілим числом: {recorded!r}")
            continue
        if after[index] > recorded:
            problems.append(f"{key} {after[index]} вище записаної стелі {recorded}")
        ceiling[key] = after[index]
    # «Нічого не змінилось» вимірюється по КАТАЛОГУ, не по лічильнику. Перша версія
    # порівнювала лише кількість непрочитаних, і прогін, який уточнив клас відмови з
    # `extractor_refused` на `content_type_mismatch`, був відкинутий як безплідний: він
    # справді не зробив жодне джерело прочитаним, і при цьому виправив неправду в записі.
    # Лічильник — це один зріз каталогу, а не сам каталог.
    if not changed:
        problems.append(
            f"прогін не змінив у каталозі нічого (непрочитаних {after}) — "
            "прогін, який нічого не змінив, не сміє записувати себе як успіх"
        )
    return problems


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="record anchors in the catalog")
    parser.add_argument("--refresh", action="store_true", help="re-read sources already read")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="re-derive from bytes an earlier run staged, instead of fetching again",
    )
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="skip sources with no staged bytes instead of fetching them",
    )
    parser.add_argument(
        "--unread",
        action="store_true",
        help="джерела без ЗАПИСУ ПРОЧИТАННЯ, навіть якщо про них щось виміряно",
    )
    parser.add_argument("--selftest", action="store_true")
    return parser


def _record(
    source: dict[str, Any], result: Capture, refusals: dict[str, dict[str, object]]
) -> dict[str, str]:
    """One refusal, held for the write. A gap named beats a gap blank.

    `retryable` is a bool, and was briefly a string to satisfy a `dict[str, str]`
    annotation. `bool("False")` is True, so every refusal read back as retryable and the
    recheck tool re-probed sources it had been told not to. The annotation was wrong; the
    value was not the place to bend.
    """
    entry: dict[str, object] = {
        "reason": str(result["refusal"]),
        "class": str(result.get("refusal_class", "unclassified")),
        "observed_on": date.today().isoformat(),
        "retryable": result.get("refusal_class", "") in RETRYABLE,
    }
    refusals[str(result["id"])] = entry
    return {
        "id": str(result["id"]),
        "reason": str(entry["reason"]),
        "class": str(entry["class"]),
    }


#: Кодування URL — НАШ бік. Дві постанови КМУ з кирилицею в шляху відмовились із
#: UnicodeEncodeError і записались у каталог класом `transport_error`, тобто наша вада
#: пішла туди як факт про джерело. Ідемпотентність окремо: подвійне кодування зробило б
#: `%20` з `%2520` і зламало б уже правильні посилання.
URI_CASES: tuple[tuple[str, str], ...] = (
    ("кирилиця у шляху", "https://x.ua/законодавство/704"),
    ("пробіл у шляху", "https://x.ua/a b"),
    ("вже закодоване лишається як є", "https://x.ua/already%20encoded"),
    ("запит зі знаками", "https://x.ua/p?a=1&b=2"),
)


def _uri_encoding_probe() -> int:
    bad = 0
    for name, uri in URI_CASES:
        encoded = encode_uri(uri)
        if not encoded.isascii():
            bad += 1
            print(f"  ✗ {name}: після кодування лишився не-ASCII: {encoded}")
        elif encode_uri(encoded) != encoded:
            bad += 1
            print(f"  ✗ {name}: кодування не ідемпотентне: {encoded} → {encode_uri(encoded)}")
    return bad


def _derived_cache_probe() -> int:
    """Кеш мусить віддавати той самий запис — і мовчати, коли байти інші або він побитий."""
    bad = 0
    with tempfile.TemporaryDirectory() as box:
        staging = Path(box)
        payload = b"<html><body>" + b"word " * 400 + b"</body></html>"
        stored = Capture(id="A", text="слово " * 300, meta={"words": 300})
        _remember(staging, payload, stored)
        back = _recall(staging, payload, "A")
        if back is None or back["text"] != stored["text"] or back["meta"] != stored["meta"]:
            bad += 1
            print(f"  ✗ кеш не повернув збережене: {back}")
        # Ті самі байти під іншим id — це той самий вміст, і запис має бути той самий.
        other = _recall(staging, payload, "B")
        if other is None or other["id"] != "B" or other["text"] != stored["text"]:
            bad += 1
            print("  ✗ ключ за байтами не працює під іншим id")
        # Інші байти — інший ключ, і кеш мусить мовчати, а не віддавати сусідній запис.
        if _recall(staging, payload + b" ", "A") is not None:
            bad += 1
            print("  ✗ кеш віддав запис для ІНШИХ байтів")
        # Побитий кеш не є підставою взяти з нього щось.
        _derived_path(staging, payload).write_text("{не json", encoding="utf-8")
        if _recall(staging, payload, "A") is not None:
            bad += 1
            print("  ✗ побитий кеш прочитано як дійсний")
    return bad


#: Проби на четверту категорію. `answers` — що каже КОРІНЬ хоста: True (будь-який HTTP-код),
#: False (транспортна невдача), None (uri не розібрати).
VANTAGE_PROBES: tuple[tuple[str, str, bool | None, str], ...] = (
    ("корінь мовчить теж — точка доступу", "reset by peer", False, "host_unreachable_from_here"),
    ("корінь відповідає — причина у шляху", "reset by peer", True, "transport_reset"),
    ("таймаут при мертвому корені", "timed out", False, "host_unreachable_from_here"),
    ("таймаут при живому корені", "timed out", True, "transport_timeout"),
    # DNS і TLS не залежать від точки доступу: імені немає ніде, сертифікат той самий.
    ("DNS не резолвиться — не точка доступу", "Name or service not known", False, "dns_unresolved"),
    ("сертифікат — не точка доступу", "CERTIFICATE_VERIFY_FAILED ssl", False, "tls_refused"),
)


def _vantage_probe() -> int:
    """Четверта категорія вимірюється, а не вгадується: питається корінь хоста."""
    bad = 0
    for name, message, answers, expected in VANTAGE_PROBES:
        original = globals()["_host_answers"]
        globals()["_host_answers"] = lambda _uri, _timeout, _a=answers: _a
        try:
            got = _transport_class(OSError(message), "https://example.invalid/x", 1)
        finally:
            globals()["_host_answers"] = original
        if got != expected:
            bad += 1
            print(f"  ✗ {name}: очікували {expected}, отримали {got}")
    # Без uri перевірка кореня не робиться взагалі — інакше кожен виклик коштував би запиту.
    if _transport_class(OSError("reset by peer")) != "transport_reset":
        bad += 1
        print("  ✗ без uri вирок змінився — перевірка кореня не сміє бути обов'язковою")
    # Сам `_host_answers`: БУДЬ-ЯКИЙ HTTP-код означає «дістались». Без цієї проби внутрішня
    # гілка не перевіряється взагалі — стуб у пробах вище підміняє всю функцію.
    forbidden: BaseException = urllib.error.HTTPError("https://x/", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
    for label, raise_with, reachable in (
        ("403 від кореня — ми дістались", forbidden, True),
        ("транспортна невдача на корені", OSError("reset by peer"), False),
    ):
        original = urllib.request.urlopen

        def _boom(*_a: object, _error: BaseException = raise_with, **_k: object) -> None:
            raise _error

        urllib.request.urlopen = _boom
        try:
            answered = _host_answers("https://example.invalid/x", 1)
        finally:
            urllib.request.urlopen = original
        if answered is not reachable:
            bad += 1
            print(f"  ✗ {label}: очікували {reachable}, отримали {answered}")
    # І розбір uri: без схеми чи хоста питати нема кого.
    if _host_answers("не-uri", 1) is not None:
        bad += 1
        print("  ✗ нерозбірний uri дав вирок замість None")
    return bad


def _concurrency_probe() -> int:
    """Правка, зроблена ПІСЛЯ старту прогону, мусить пережити запис.

    Це не гіпотетика: 2026-08-29 попередниця `commit` тримала знімок каталогу з моменту
    старту і за секунди не стерла 5245 рядків третьої сесії. Знімок не змерджився б —
    він стер би все. Проба ставить рівно це: між читанням і записом хтось дописав поле,
    і воно мусить бути на місці, разом із моїм.
    """
    bad = 0
    with tempfile.TemporaryDirectory() as box:
        catalog_path = Path(box) / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {"id": "A", "ingestible": True, "canonical_title": "A"},
                        {"id": "B", "ingestible": True, "canonical_title": "B"},
                    ],
                    "evidence_ceiling": {
                        "sources_without_evidence": 2,
                        "ingestible_without_evidence": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        # Хтось інший дописує поле, поки прогін іде.
        concurrent = json.loads(catalog_path.read_text(encoding="utf-8"))
        concurrent["sources"][1]["written_by_another_session"] = True
        catalog_path.write_text(json.dumps(concurrent), encoding="utf-8")

        captures = ROOT / "config/corpus/captures"
        captures.mkdir(parents=True, exist_ok=True)
        result = Capture(
            id="A",
            text="слово " * 300,
            meta={"fetched_on": date.today().isoformat(), "words": 300},
        )
        problems = commit({"A": result}, {}, catalog_path)
        after = json.loads(catalog_path.read_text(encoding="utf-8"))
        by = {s["id"]: s for s in after["sources"]}
        if not by["B"].get("written_by_another_session"):
            bad += 1
            print(f"  ✗ правка іншої сесії стерта записом ({problems})")
        if not by["A"].get("integrity_anchor"):
            bad += 1
            print(f"  ✗ власний доказ не записаний ({problems})")
        (captures / "A.txt").unlink(missing_ok=True)

        # І другий бік: джерело, ЗНЯТЕ кимось із каталогу під час прогону, не сміє
        # повернутись сюди. Відтворити його означало б мовчки скасувати чиєсь видалення.
        deleted = json.loads(catalog_path.read_text(encoding="utf-8"))
        deleted["sources"] = [s for s in deleted["sources"] if s["id"] != "B"]
        catalog_path.write_text(json.dumps(deleted), encoding="utf-8")
        gone = Capture(id="B", text="слово " * 300, meta={"fetched_on": date.today().isoformat()})
        said = " ".join(commit({"B": gone}, {}, catalog_path))
        back = json.loads(catalog_path.read_text(encoding="utf-8"))
        if any(s["id"] == "B" for s in back["sources"]):
            bad += 1
            print("  ✗ зняте джерело відтворено записом")
        if "зникли з каталогу" not in said:
            bad += 1
            print(f"  ✗ зникнення не назване: {said!r}")
        (captures / "B.txt").unlink(missing_ok=True)
    return bad


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.selftest:
        return selftest()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    staging = ROOT / "var/evidence-capture"
    targets = [
        s for s in catalog["sources"] if _needs_evidence(s, arguments.refresh, arguments.unread)
    ]
    if arguments.cached_only:
        targets = [s for s in targets if _cached(staging, str(s["id"])) is not None]
    if arguments.limit is not None:
        targets = targets[: arguments.limit]

    anchored, refused = 0, []
    updates: dict[str, Capture] = {}
    refusals: dict[str, dict[str, object]] = {}
    for source in targets:
        result = capture_one(source, arguments.timeout, staging, arguments.from_cache)
        if "refusal" in result:
            refused.append(_record(source, result, refusals))
            print(f"  ✗ {result['id']:30} {result['refusal'][:110]}")
            continue
        anchored += 1
        updates[str(result["id"])] = result
        meta = result["meta"]
        served, extracted = meta[BYTES_SCOPE], meta[TEXT_SCOPE]
        print(
            f"  ✓ {result['id']:30} {served['bytes'] / 1e6:6.2f} МБ  "
            f"{extracted['pages']:4} стор.  {extracted['words']:7} слів  "
            f"{extracted['extractor']}"
        )

    problems = commit(updates, refusals) if arguments.write else []
    for problem in problems:
        print(f"  ✗ РАТЧЕТ: {problem}")
    print(
        json.dumps(
            {
                "considered": len(targets),
                "anchored": anchored,
                "refused": len(refused),
                "written": arguments.write and not problems,
                "ungrounded_now": {
                    "sources": ungrounded(json.loads(CATALOG.read_text(encoding="utf-8")))[0],
                    "ingestible": ungrounded(json.loads(CATALOG.read_text(encoding="utf-8")))[1],
                },
                "ratchet_problems": problems,
                "refusals": refused,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
