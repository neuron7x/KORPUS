# Extraction fidelity: issue 132

## Failure modes and contract

A successful extraction must not silently omit a nonblank PDF page, collapse Word
table values into unrelated paragraphs, or address a quotation with a heading that
belongs to an earlier part of the same page. These are independent failure modes;
one aggregate text-length threshold cannot establish document completeness.

This change strengthens deterministic extraction and citation addressing. It does
not certify OCR accuracy, table interpretation, or domain correctness. Original
uploaded bytes remain the source artifact, and the existing review and publication
controls remain responsible for admitting extracted evidence.

## PDF page completeness

Every PDF page is inspected independently after embedded text extraction. Image or
form painting operators require OCR even when the same page has an embedded text
header. A page with no embedded text but visible text/vector painting also requires
OCR. A page with no painting operations is retained as a genuinely blank page and
does not require OCR. An entirely empty document is still refused.

When OCR is disabled, the document fails with the original page numbers that need
OCR. When enabled, only those pages are rendered with bounded original page numbers.
The renderer's file inventory and the OCR result inventory must match that selection
exactly. Missing, extra, reordered, or duplicate results cannot become a successful
partial extraction. OCR replaces only selected pages; unaffected embedded text and
blank page identities are preserved.

OCR must yield nonempty text. On pages that already have native text, the OCR result
must also contain that complete native text after whitespace normalization. If it
does not, extraction fails rather than quietly replacing known evidence with a
weaker reading or concatenating unrelated readings into a fabricated quotation.
An OCR result that merely repeats the native header also fails as incomplete. This
intentionally rejects some difficult layouts, decorative images, and legitimate
OCR variations.

The existing parser worker memory, execution-time, output-size, and PDF-page limits
remain in force. Rendering and recognition use the same monotonic deadline. Page
inspection checks that deadline before and after examining each page. The parser's
resource-limit refusal remains terminal rather than triggering lenient retries or
OCR. The extraction method records mixed OCR/native documents as `pdf_ocr_mixed`,
with the existing owner-restricted and lenient provenance suffixes where applicable.

This is conservative completeness detection, not visual understanding. A logo or
text-bearing form can require OCR even when no new words are present. Vector diagrams
on pages with native text are not interpreted. OCR can still misrecognize scanned
words; human review remains necessary for sources whose correctness matters.

## Word table representation

OOXML body blocks are traversed in document order. Paragraphs remain paragraphs;
tables remain ordered rows and cells. Headers retain their position relative to
their columns. Each table is represented as tab-separated rows whose cells are JSON
strings. For example, the three cells `A01`, an empty value, and `20` become:

```text
"A01"\t""\t"20"
```

Here `\t` denotes an actual tab delimiter in canonical extracted text. A cell's
literal tabs, quotes, backslashes, and internal paragraph breaks are JSON-escaped.
Repeated literal spaces are escaped where necessary to survive the existing text
normalizer. Thus a trailing empty cell remains `""`; trimming a span cannot erase it
as invisible trailing whitespace. Quoting is structural encoding and does not supply
missing facts. Ordinary paragraph trimming and Unicode normalization still apply.
The source text endpoint exposes this canonical representation for inspection.

Merged cells, omitted grid positions, nested tables, wrapped rows/cells, and rows
whose widths disagree with their grid are explicitly refused. A unit-width grid
span is accepted. Standard implicit grids and entirely empty cells remain supported.
These refusals avoid pretending that unsupported geometry has a known relationship.
Large table text still obeys configured span and worker output bounds; this change
does not add a semantic table query engine or invent repeated headers in quotations.

## Section addresses and exact quotations

Span construction stops at every recognized structural heading. Overlap is retained
inside each section and never reaches back into a previous section. A span therefore
contains only text addressed by the heading active at its start; text before the
first heading remains unlabelled. Page boundaries, exact source substrings, ordinal
order, maximum size/count, and strict forward progress remain construction rules.
The answer service uses its existing span section and quote-offset verification.
No answer-service or authorization changes are needed for this correction.

## Executable controls

The fixtures contain only neutral archive/color data. They use the locked `pypdf`
dependency and the Python standard library, with real PDF image/text operators and
minimal OPC Word archives. No optional PDF/Word generation library is skipped into
a passing result.

| Control | Evidence established |
| --- | --- |
| `test_pdf_page_fidelity.py` | Real mixed/header-plus-image/blank PDF parsing; explicit disabled-OCR refusal; controlled OCR selection, original page numbers, native-text preservation, result inventory, deadline, page cap, output cap |
| `test_docx_table_fidelity.py` | Real archive/XML parsing, ordered headers/values/empty cells, escaped delimiters, exact span substrings, ordinary positive cases, explicit unsupported geometry and worker output bounds |
| `test_section_span_fidelity.py` | Two-section short-page regression, HTTP citation address and exact quote/hash offsets, bounded overlap/forward progress/coverage, span-count refusal |

All three files are included in the existing multi-seed determinism gate. Mutation
controls M810–M815 challenge image loss behind a text header, discarded empty table
cells, spans crossing headings, OCR replacing native text, tables hidden inside
paragraph textboxes, and Unicode cell separators forging extra rows. These are focused
causal checks; a canonical mutation report must still obey the existing trusted
runtime and full-campaign requirements. Controlled OCR subprocess tests do not
constitute a native Tesseract recognition benchmark.

Independent review also exercised a real VML textbox containing a table. Paragraph
extraction now explicitly refuses descendant tables, which otherwise bypassed the
table serializer. U+0085, U+2028, and U+2029 are escaped inside JSON cells so that
splitlines-based consumers retain the original row inventory. Ordinary Unicode
words remain readable and searchable, and decoding recovers each original separator.
