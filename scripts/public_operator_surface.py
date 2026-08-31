#!/usr/bin/env python3
"""Що саме є операторською поверхнею — похідно, а не переліком імен.

Правило жило трьома копіями: `serve_public.sh` прибирав три файли, `deploy_public_web.py`
виключав ті самі три з маніфесту, `deploy/public/nginx.conf` віддавав 404 на одне ім'я.
Усі три твердили «консолі не публікуються», усі три перелічували три імені, поверхня
виросла до восьми — і 31.08.2026 публічний edge віддавав `console.css`,
`console_accounts.js`, `console_mutations.js`, `console_readonly.js` по 200 зі справжнім
вмістом. Тут воно живе один раз і як ПРЕДМЕТ, а не як прапорець на розгортальнику:
модуль імпортується з коду й запускається з оболонки.

    public_operator_surface.py apps/web/public
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Файли, без яких читацька сторінка не працює. Дублюється значенням у
#: `deploy_public_web.REQUIRED`: спільна константа зробила б так, що правило й те, що
#: воно охороняє, змінюються одним рухом.
REQUIRED = frozenset({"index.html", "app.js", "styles.css", "tokens.css", "sw.js", "config.js"})

#: Дві сторінки-корені. Усе, чого досягає перша й не досягає друга, — операторське.
OPERATOR_ENTRY = "console.html"
READER_ENTRY = "index.html"

#: Закриття ходить тим, що сторінка ВАНТАЖИТЬ, а не тим, на що вона ПОСИЛАЄТЬСЯ.
#: Різниця не косметична: `index.html` містить `<a href="/console.html">Консоль</a>`,
#: і якби перехід рахувався завантаженням, закриття читача поглинуло б усю консоль,
#: різниця стала б порожньою, і правило мовчки оголосило б, що операторського немає
#: взагалі. Тому теґ `<a>` не веде нікуди: вантажать `<script src>` і `<link href>`,
#: а всередині модуля — статичний і динамічний імпорт. Форма, якої тут бракує, дала б
#: закриття ЧИТАЧА вужчим за справжнє, тобто прибрала б із публікації те, що він
#: вантажить, — тому перелік звіряється тестом за значенням, а не лише правилом.
_LINK_PATTERNS = (
    re.compile(r'<script[^>]*\ssrc="(?P<target>/?[A-Za-z0-9_.\-]+\.js)"'),
    re.compile(r'<link[^>]*\shref="(?P<target>/?[A-Za-z0-9_.\-]+\.css)"'),
    re.compile(r'from\s+"(?P<target>\./[A-Za-z0-9_.\-]+\.js)"'),
    re.compile(r'import\(\s*"(?P<target>\./[A-Za-z0-9_.\-]+\.js)"'),
    re.compile(r'serviceWorker\.register\(\s*"(?P<target>/?[A-Za-z0-9_.\-]+\.js)"'),
)


def _reachable(source: Path, entry: str) -> set[str]:
    """Файли, яких досягає сторінка. Порожньо, якщо самої сторінки немає."""
    seen: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        path = source / name
        if not path.is_file():
            continue
        seen.add(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in _LINK_PATTERNS:
            for match in pattern.finditer(text):
                pending.append(match.group("target").lstrip("./").lstrip("/"))
    return seen


def operator_only(source: Path) -> set[str]:
    """Операторська поверхня = закриття консолі мінус закриття читача.

    Перелік імен тут стояв раніше, і він відстав: поверхня виросла до семи файлів,
    перелік лишився з трьома, тож `console.css`, `console_accounts.js`,
    `console_mutations.js` і `console_readonly.js` пішли в публічний edge і
    віддавалися з нього. Твердження було про КОНСОЛЬ, а правило — про три імені.
    Похідне визначення не може відстати: новий файл консолі потрапляє в закриття
    тим самим імпортом, яким його підключили.
    """
    withheld = _reachable(source, OPERATOR_ENTRY) - _reachable(source, READER_ENTRY)
    # Правило, що зібралося прибрати те, без чого читач не працює, помиляється саме
    # тоді, коли помилку найважче помітити: сторінка вийде в світ порожньою, а гейт
    # про консолі при цьому позеленіє. Тому суперечність — відмова, не попередження.
    essential = set(REQUIRED) & withheld
    if essential:
        raise ValueError(f"operator rule would withhold reader essentials: {sorted(essential)}")
    return withheld


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    for name in sorted(operator_only(Path(argv[1]))):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
