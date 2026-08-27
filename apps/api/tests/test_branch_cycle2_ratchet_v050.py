from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from korpus.application import checkout, service_levels, tuning
from korpus.application.retrieval import DEFAULT_BM25_PARAMETERS, DEFAULT_RETRIEVAL_WEIGHTS
from korpus.infrastructure import object_store as osmod
from korpus.infrastructure import pdf_extraction as pdf
from korpus.security import scanning


def test_tuning_validation_ratchet() -> None:
    with pytest.raises(ValueError, match="relevance"):
        tuning.JudgedCandidate("x", 4)
    with pytest.raises(ValueError, match="component scores"):
        tuning.JudgedCandidate("x", 1, authority_score=2)
    good = tuning.JudgedCandidate("relevant", 1)
    zero = tuning.JudgedCandidate("none", 0)
    with pytest.raises(ValueError, match="incomplete"):
        tuning.JudgedQuery("", "q", (good,))
    with pytest.raises(ValueError, match="relevant evidence"):
        tuning.JudgedQuery("q1", "query", (zero,))
    with pytest.raises(ValueError, match="dataset is empty"):
        tuning.evaluate_ranking([], DEFAULT_RETRIEVAL_WEIGHTS, DEFAULT_BM25_PARAMETERS)
    with pytest.raises(ValueError, match="evenly divide"):
        list(tuning._simplex_weight_candidates(0.3))
    with pytest.raises(ValueError, match="at least two"):
        tuning.tune_ranking(
            [tuning.JudgedQuery("q1", "query", (good,))],
            [tuning.JudgedQuery("v1", "query", (good,))],
        )


def test_service_level_shape_fail_closed_matrix() -> None:
    assert service_levels._count_5xx({"statuses": []}) == 0
    result = service_levels.evaluate_load_slos({"soak": [], "cold_first_request": []})
    assert not result["load_slo_steady_p95"] and not result["load_slo_cold_start"]
    result = service_levels.evaluate_load_slos(
        {
            "soak": {"p95_seconds": 1, "refusal_reasons": [], "decisions": []},
            "cold_first_request": {"seconds": 1},
        }
    )
    assert result["load_slo_no_subject_throttle_rated"] and result["load_slo_no_retrieval_deadline"]
    result = service_levels.evaluate_load_slos(
        {
            "soak": {
                "p95_seconds": 1,
                "statuses": {"500": 1},
                "refusal_reasons": {service_levels.SUBJECT_THROTTLE_REASON: 1},
                "decisions": {"retrieval_deadline_exceeded": 1},
            },
            "cold_first_request": {"seconds": 1},
        }
    )
    assert (
        not result["load_slo_no_5xx_rated"]
        and not result["load_slo_no_subject_throttle_rated"]
        and not result["load_slo_no_retrieval_deadline"]
    )
    for impossible in (-1, float("nan"), float("inf")):
        result = service_levels.evaluate_load_slos(
            {
                "soak": {"p95_seconds": impossible},
                "cold_first_request": {"seconds": impossible},
            }
        )
        assert result["load_slo_steady_p95"] is False
        assert result["load_slo_cold_start"] is False
    assert (
        service_levels.evaluate_load_slos(
            {
                "soak": {"p95_seconds": 1, "statuses": {"500": -1}},
                "cold_first_request": {"seconds": 1},
            }
        )["load_slo_no_5xx_rated"]
        is False
    )


class Accounts:
    def __init__(self, account):
        self.account = account

    def get_account(self, account_id):
        del account_id
        return self.account


class Subs:
    def __init__(self, plan):
        self.plan = plan

    def get_plan_by_code(self, code):
        del code
        return self.plan


class Service:
    def __init__(self, active=None):
        self.active = active

    def active_subscription(self, account_id):
        del account_id
        return self.active

    def start_subscription(self, actor, account, plan):
        del actor, account, plan
        return SimpleNamespace(id=uuid4())


class Provider:
    name = "fake"

    def create_checkout(self, **kwargs):
        return checkout.CheckoutDescriptor(
            kwargs["subscription"].id, "fake", "https://pay", "POST", {}
        )


def test_checkout_fail_closed_branch_matrix() -> None:
    aid = uuid4()
    with pytest.raises(checkout.CheckoutUnavailable, match="account does not exist"):
        checkout.CheckoutService(
            Accounts(None), Subs(None), Service(), Provider(), "https://k"
        ).start("u", aid, "p")
    account = SimpleNamespace(id=aid)
    with pytest.raises(checkout.CheckoutUnavailable, match="active subscription"):
        checkout.CheckoutService(
            Accounts(account), Subs(None), Service(active=object()), Provider(), "https://k"
        ).start("u", aid, "p")
    with pytest.raises(checkout.PlanNotFound):
        checkout.CheckoutService(
            Accounts(account), Subs(None), Service(), Provider(), "https://k"
        ).start("u", aid, "p")
    unsellable = SimpleNamespace(price_minor=None, currency=None)
    with pytest.raises(checkout.CheckoutUnavailable, match="sellable price"):
        checkout.CheckoutService(
            Accounts(account), Subs(unsellable), Service(), Provider(), "https://k"
        ).start("u", aid, "p")
    sellable = SimpleNamespace(price_minor=100, currency="UAH")
    with pytest.raises(checkout.CheckoutUnavailable, match="public base URL"):
        checkout.CheckoutService(
            Accounts(account), Subs(sellable), Service(), Provider(), ""
        ).start("u", aid, "p")
    descriptor = checkout.CheckoutService(
        Accounts(account), Subs(sellable), Service(), Provider(), "https://k/"
    ).start("u", aid, "p")
    assert descriptor.provider == "fake"


def test_scanner_config_missing_size_and_response_matrix(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scanning.DisabledMalwareScanner().scan(tmp_path / "missing")
    with pytest.raises(ValueError, match="invalid clamd"):
        scanning.ClamdInstreamScanner("", 0)
    p = tmp_path / "x"
    p.write_bytes(b"12345")
    with pytest.raises(ValueError, match="size limit"):
        scanning.ClamdInstreamScanner("localhost", max_bytes=4).scan(p)

    class Conn:
        def __init__(self, chunks):
            self.chunks = iter(chunks)

        def recv(self, n):
            del n
            return next(self.chunks, b"")

    with pytest.raises(scanning.MalwareScannerUnavailable, match="empty"):
        scanning.ClamdInstreamScanner._read_response(Conn([]))
    assert (
        scanning.ClamdInstreamScanner._read_response(Conn([b"stream: OK\n", b"ignored"]))
        == "stream: OK"
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Body:
    def __init__(self, data: bytes, close=None):
        self.io = BytesIO(data)
        self.close = close

    def read(self, n=-1):
        return self.io.read(n)


class S3:
    def __init__(self):
        self.objects = {}

    def head_object(self, **kw):
        key = kw["Key"]
        if key not in self.objects:
            e = RuntimeError("missing")
            e.response = {"Error": {"Code": "404"}}
            raise e
        return self.objects[key]["head"]

    def put_object(self, **kw):
        body = kw["Body"]
        data = body.read() if hasattr(body, "read") else bytes(body)
        self.objects[kw["Key"]] = {
            "data": data,
            "head": {
                "Metadata": kw["Metadata"],
                "ContentLength": len(data),
                "ChecksumSHA256": kw["ChecksumSHA256"],
            },
        }

    def get_object(self, **kw):
        item = self.objects[kw["Key"]]
        return {
            "Body": Body(item["data"], None),
            "Metadata": item["head"]["Metadata"],
            "ContentLength": len(item["data"]),
            "ChecksumSHA256": item["head"]["ChecksumSHA256"],
        }

    def list_objects_v2(self, **kw):
        return {"Contents": [], "IsTruncated": False}


def test_remaining_object_store_close_and_put_path_edges(tmp_path: Path) -> None:
    data = b"abc"
    digest = _digest(data)
    p = tmp_path / "p"
    p.write_bytes(data)
    client = S3()
    store = osmod.S3ObjectStore(
        bucket="bucket", prefix="objects", client=client, max_object_bytes=64
    )
    key = store.put_path(p, digest, "x")
    assert store.get(key) == data  # non-callable close normal path
    out = tmp_path / "out"
    store.get_to_path(key, out)
    assert out.read_bytes() == data

    # callable close on declared-oversize path
    closed = []
    store.client.get_object = lambda **kw: {
        "Body": Body(data, lambda: closed.append(True)),
        "Metadata": {"sha256": digest},
        "ContentLength": 999,
    }
    with pytest.raises(RuntimeError, match="read limit"):
        store.get_to_path(key, tmp_path / "big")
    assert closed


def test_pdf_ocr_renderer_and_image_loop_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "x.pdf"
    source.write_bytes(b"pdf")
    calls = []

    def run(args, **kwargs):
        del kwargs
        calls.append(args[0])
        if args[0] == "pdftoppm":
            Path(str(args[-1]) + "-1.png").write_bytes(b"img")
            return SimpleNamespace(stdout=b"")
        return SimpleNamespace(stdout=b"OCR")

    monkeypatch.setattr(pdf.subprocess, "run", run)
    pages = pdf._ocr_pages(source, "eng", 10**12, 2, lambda s: s.lower())
    assert pages[0].text == "ocr" and calls == ["pdftoppm", "tesseract"]

    def too_many(args, **kwargs):
        del kwargs
        if args[0] == "pdftoppm":
            Path(str(args[-1]) + "-1.png").write_bytes(b"1")
            Path(str(args[-1]) + "-2.png").write_bytes(b"2")
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(pdf.subprocess, "run", too_many)
    with pytest.raises(ValueError, match="page limit"):
        pdf._ocr_pages(source, "eng", 10**12, 1, str)
