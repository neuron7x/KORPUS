# KORPUS content and typography standard

## Decision rule

Interface language must help the user complete the current action. Decorative,
promotional, duplicated, or unverifiable copy is removed. Safety and authority
limits are never shortened until their meaning changes.

## Reading contract

- Default body size: 16 px.
- Query and answer size: 18 px on wide screens.
- Reading measure: at most 68 characters.
- Reading line height: 1.65.
- Paragraphs and controls use left/start alignment. Centering is limited to short prompts.
- Capital letters are limited to short status labels.
- One sentence carries one operational idea.
- Every action begins with a concrete verb.
- Dynamic user, answer, and evidence text uses `dir="auto"` for Ukrainian LTR and Hebrew RTL.
- Color never carries state without text or another non-color indicator.

## Language contract

Ukrainian is the canonical interface language and follows the official Ukrainian
orthography. Use common words, active voice, literal meaning, and the shortest
sentence that preserves the operational or legal distinction.

Hebrew is treated as a right-to-left language, not as visually reversed Ukrainian.
Direction is expressed with HTML `dir`, text remains in logical Unicode order, and
mixed identifiers or numerals are isolated by their nearest semantic element.

## Evidence base

- W3C, Clear and Understandable Content:
  https://www.w3.org/WAI/WCAG2/supplemental/objectives/o3-clear-content/
- W3C, Visual Presentation (WCAG 2.2):
  https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html
- W3C, Text Spacing (WCAG 2.2):
  https://www.w3.org/WAI/WCAG22/Understanding/text-spacing
- W3C, Structural markup and right-to-left text:
  https://www.w3.org/International/questions/qa-html-dir.en.html
- W3C, Hebrew and other RTL authoring tutorial:
  https://www.w3.org/International/tutorials/bidi-xhtml/Overview.en
- National Commission on State Language Standards, Ukrainian orthography (2026):
  https://mova.gov.ua/storage/app/sites/19/2026/rishennja-komisiji/01-03/sdm-ukrayinskii-pravopis-vidannia.pdf

No claim that a particular font or color can manipulate purchasing behavior is part
of this standard. Such a claim requires a preregistered product experiment with a
task-completion, comprehension, error, and accessibility outcome.
