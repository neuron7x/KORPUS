from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = {
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Strict-Transport-Security",
    "Content-Security-Policy",
}
CONFIGS = (
    ROOT / "apps/web/nginx.conf",
    ROOT / "apps/web/nginx.cloudrun.conf",
    ROOT / "deploy/public/nginx.conf",
)


def _location_bodies(source: str) -> list[str]:
    bodies: list[str] = []
    pos = 0
    while True:
        start = source.find("location ", pos)
        if start < 0:
            return bodies
        brace = source.find("{", start)
        if brace < 0:
            raise AssertionError("location without opening brace")
        depth = 1
        quote: str | None = None
        escaped = False
        index = brace + 1
        while index < len(source) and depth:
            char = source[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        if depth:
            raise AssertionError("unterminated nginx location block")
        bodies.append(source[brace + 1 : index - 1])
        pos = index


def _headers(body: str) -> set[str]:
    headers = set()
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("add_header "):
            parts = line.split(None, 2)
            if len(parts) >= 2:
                headers.add(parts[1])
    return headers


def test_all_deployed_edges_persist_https_and_do_not_lose_headers_by_inheritance() -> None:
    for path in CONFIGS:
        source = path.read_text(encoding="utf-8")
        assert 'add_header Strict-Transport-Security "max-age=31536000" always;' in source, path
        carrying = [body for body in _location_bodies(source) if "add_header " in body]
        assert carrying, path
        for body in carrying:
            missing = REQUIRED - _headers(body)
            assert not missing, f"{path}: location overrides add_header but drops {sorted(missing)}"


def test_header_invariant_can_fail_on_cloudrun_refusal_location() -> None:
    path = ROOT / "apps/web/nginx.cloudrun.conf"
    source = path.read_text(encoding="utf-8")
    mutated = source.replace(
        '      add_header Strict-Transport-Security "max-age=31536000" always;\n',
        "",
        1,
    )
    assert mutated != source
    carrying = [body for body in _location_bodies(mutated) if "add_header " in body]
    assert any("Strict-Transport-Security" not in _headers(body) for body in carrying)
