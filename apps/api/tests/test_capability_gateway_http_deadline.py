import httpx
import pytest
from korpus.application.capability_gateway.adapters import AdapterExecutionFailed
from korpus.infrastructure.integrations import http

from apps.api.tests.test_capability_gateway_http_adapter import _context, _plan, _request, _spec


class _Clock:
    now = 100.0


class _Stream(httpx.SyncByteStream):
    def __init__(self, clock, delays):
        self.clock = clock
        self.delays = delays
        self.closed = False
        self.reads = 0

    def __iter__(self):
        for delay, chunk in zip(self.delays, [b'{"value":', b'"ok"', b"}"], strict=True):
            self.clock.now += delay
            self.reads += 1
            yield chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "header_delay,delays,success",
    [
        (0, [0.1, 0.1, 0.1], True),
        (0, [0.2, 0.2, 0.2], False),
        (0.3, [0.1, 0.1, 0.1], False),
        (0.5, [0, 0, 0], False),
        (0, [0, 0, 0.5], False),
    ],
)
def test_total_deadline_covers_headers_and_stream(monkeypatch, header_delay, delays, success):
    clock = _Clock()
    monkeypatch.setattr(http, "monotonic", lambda: clock.now)
    stream = _Stream(clock, delays)

    def transport(request):
        clock.now += header_delay
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = http.GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example",
            plan_builder=_plan,
        )
        kwargs = dict(spec=_spec(), request=_request(), context=_context(), logical_resource="r")
        if success:
            assert adapter.execute(**kwargs).output == {"value": "ok"}
        else:
            with pytest.raises(AdapterExecutionFailed, match="total deadline exceeded"):
                adapter.execute(**kwargs)
    assert stream.closed
    if header_delay == 0.5:
        assert stream.reads == 0


def test_plan_consumes_deadline_before_network(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(http, "monotonic", lambda: clock.now)
    calls = []

    def plan(payload, resource):
        clock.now += 0.5
        return _plan(payload, resource)

    with httpx.Client(transport=httpx.MockTransport(calls.append)) as client:
        adapter = http.GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example",
            plan_builder=plan,
        )
        with pytest.raises(AdapterExecutionFailed, match="total deadline exceeded"):
            adapter.execute(
                spec=_spec(),
                request=_request(),
                context=_context(),
                logical_resource="r",
            )
    assert calls == []


@pytest.mark.parametrize("stage", ["eof", "decode"])
def test_deadline_checked_after_eof_and_decoding(monkeypatch, stage):
    clock = _Clock()
    monkeypatch.setattr(http, "monotonic", lambda: clock.now)

    class Stream(_Stream):
        def __iter__(self):
            yield from super().__iter__()
            if stage == "eof":
                clock.now += 0.5

    original = http.json.loads

    def loads(body):
        clock.now += 0.5
        return original(body)

    if stage == "decode":
        monkeypatch.setattr(http.json, "loads", loads)
    stream = Stream(clock, [0, 0, 0])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=stream,
        )
    )
    with httpx.Client(transport=transport) as client:
        adapter = http.GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example",
            plan_builder=_plan,
        )
        with pytest.raises(AdapterExecutionFailed, match="total deadline exceeded"):
            adapter.execute(
                spec=_spec(),
                request=_request(),
                context=_context(),
                logical_resource="r",
            )
    assert stream.closed


def test_plan_time_reduces_transport_timeout(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(http, "monotonic", lambda: clock.now)
    seen = []

    def plan(payload, resource):
        clock.now += 0.2
        return _plan(payload, resource)

    def transport(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"value": "ok"})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = http.GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example",
            plan_builder=plan,
        )
        assert adapter.execute(
            spec=_spec(),
            request=_request(),
            context=_context(),
            logical_resource="r",
        ).output == {"value": "ok"}
    assert len(seen) == 1
    assert all(value == pytest.approx(0.3) for value in seen[0].values())
