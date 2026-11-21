"""Exercise a running KORPUS service with real credentials and a neutral smoke corpus."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pilot_acceptance_contract import (
    Credentials,
    Fixture,
    ProbeFailure,
    answer_citations,
    bootstrap_identity,
    identifier,
    object_payload,
    require,
    require_abstention,
    require_reader,
    runtime_facts,
    sha256,
    validate_scope,
    validate_transition,
    validate_upload,
    verify_citation,
)
from pilot_acceptance_http import LiveHTTP, ingestion_result, read_credential

STAGES = ("metadata_reviewed", "content_reviewed", "approved")
REVIEW_PERMISSIONS = ("document:review_metadata", "document:review", "document:approve")


@dataclass(frozen=True)
class Options:
    base_url: str
    corpus_id: str
    exercise_fixture: bool = False
    timeout: float = 15.0
    job_timeout: float = 60.0


class PilotAcceptance:
    def __init__(self, options: Options, credentials: Credentials) -> None:
        self.options = options
        self.credentials = credentials
        self.fixture = Fixture(options.corpus_id)
        self.http: LiveHTTP
        self.mode = ""
        self.document_id = ""
        self.version_id = ""
        self.stage = "configuration"
        self.report: dict[str, Any] = {
            "schema": "korpus.live-pilot-acceptance.v1",
            "status": "FAIL",
            "measured_at": datetime.now(UTC).isoformat(),
            "transport": "live_http",
            "scope": "synthetic_fixture_authenticated_api_journey",
            "browser_ui_verified": False,
            "production_authorized": False,
            "completed_checks": [],
        }

    def passed(self) -> None:
        self.report["completed_checks"].append(self.stage)

    def run(self) -> dict[str, Any]:
        try:
            validate_scope(self.options.corpus_id, len(self.credentials.readers))
            require(self.options.exercise_fixture, "--exercise-fixture is required before mutation")
            require(0 < self.options.job_timeout <= 300, "job timeout must be in (0, 300] seconds")
            self.http = LiveHTTP(self.options.base_url, self.options.timeout)
            try:
                self.report["base_url"] = self.http.base_url
                self.identities()
                self.authentication_denials()
                self.upload()
                self.quarantined_readers()
                self.review()
                self.approved_readers()
                self.outsider_denial()
                self.report["status"] = "PASS"
            finally:
                self.http.close()
        except ProbeFailure as exc:
            self.report["failed_check"] = self.stage
            self.report["failure"] = str(exc)
        return self.report

    def bootstrap(self, token: str) -> dict[str, Any]:
        return object_payload(self.http.request("GET", "/v1/client/bootstrap", token).expect(200))

    def identities(self) -> None:
        self.stage = "identity_preflight"
        owner = self.bootstrap(self.credentials.owner)
        owner_subject, permissions = bootstrap_identity(owner, self.options.corpus_id)
        require("document:ingest" in permissions, "owner lacks ingestion permission")
        capabilities = object_payload(owner.get("capabilities"))
        self.mode = str(capabilities.get("ingestion_mode"))
        require(self.mode in {"synchronous", "durable_async"}, "unsupported ingestion mode")
        self.report.update(runtime_facts(owner))
        self.report["ingestion_mode"] = self.mode
        reviewers = self.reviewer_identities()
        seen = {owner_subject, *reviewers}
        subjects = []
        for token in self.credentials.readers:
            subject, grants = bootstrap_identity(self.bootstrap(token), self.options.corpus_id)
            require(
                subject not in seen, "readers must be distinct from owner, reviewers and each other"
            )
            require_reader(grants)
            seen.add(subject)
            subjects.append(sha256(subject))
        self.report["reader_subject_hashes"] = subjects
        self.report["reader_count"] = len(subjects)
        self.passed()

    def reviewer_identities(self) -> list[str]:
        subjects = []
        for token, permission in zip(self.credentials.reviewers, REVIEW_PERMISSIONS, strict=True):
            subject, grants = bootstrap_identity(self.bootstrap(token), self.options.corpus_id)
            require(permission in grants, "review credential lacks its stage permission")
            subjects.append(subject)
        return subjects

    def authentication_denials(self) -> None:
        self.stage = "authentication_denials"
        for token in (None, "invalid-acceptance-credential"):
            self.http.request("POST", "/v1/answers", token, self.fixture.query()).expect(401)
        self.passed()

    def upload(self) -> None:
        self.stage = "fixture_upload"
        self.report["fixture"] = {
            "corpus_id": self.fixture.corpus_id,
            "marker": self.fixture.marker,
            "source_sha256": sha256(self.fixture.content),
            "as_of": self.fixture.as_of.isoformat(),
            "cleanup": "not_attempted",
        }
        payload = ingestion_result(
            self.http,
            self.credentials.owner,
            self.fixture,
            self.mode,
            self.options.job_timeout,
            self.report["fixture"],
        )
        self.document_id, self.version_id = validate_upload(payload, self.fixture)
        self.report["fixture"].update(document_id=self.document_id, version_id=self.version_id)
        self.report["fixture"]["retained"] = True
        self.passed()

    def quarantined_readers(self) -> None:
        for index, token in enumerate(self.credentials.readers, 1):
            self.stage = f"reader_{index}_quarantine"
            answer = self.http.request("POST", "/v1/answers", token, self.fixture.query()).expect(
                200
            )
            require_abstention(answer)
            spans = self.http.request(
                "GET", f"/v1/document-versions/{self.version_id}/spans", token
            ).expect(200)
            require(spans == [], "quarantined spans were disclosed")
            self.passed()
            self.stage = f"reader_{index}_write_denials"
            self.write_denials(token)
            self.passed()

    def write_denials(self, token: str) -> None:
        path = (
            "/v1/documents/ingest" if self.mode == "synchronous" else "/v1/ingestion-jobs/documents"
        )
        self.http.request("POST", path, token, fixture=self.fixture).expect(403)
        self.http.request(
            "POST",
            f"/v1/document-versions/{self.version_id}/review",
            token,
            {"target": "metadata_reviewed", "note": "synthetic denial probe"},
        ).expect(403)

    def review(self) -> None:
        for sequence, (target, token) in enumerate(
            zip(STAGES, self.credentials.reviewers, strict=True), 1
        ):
            self.stage = f"fixture_review_{target}"
            body: dict[str, object] = {
                "target": target,
                "note": f"Explicit synthetic acceptance fixture transition: {target}",
            }
            payload = self.http.request(
                "POST", f"/v1/document-versions/{self.version_id}/review", token, body
            ).expect(200)
            validate_transition(payload, self.version_id, target, sequence)
            self.passed()

    def approved_readers(self) -> None:
        for index, token in enumerate(self.credentials.readers, 1):
            self.stage = f"reader_{index}_answer_and_sources"
            self.answer_and_sources(token)
            self.passed()
            self.stage = f"reader_{index}_temporal_and_scope_denials"
            self.temporal_and_scope_denials(token)
            self.passed()

    def answer_and_sources(self, token: str) -> None:
        answer = self.http.request("POST", "/v1/answers", token, self.fixture.query()).expect(200)
        citations = answer_citations(answer, self.fixture)
        span_ids = []
        for citation in citations:
            span_id = identifier(citation.get("span_id"))
            path = f"/v1/spans/{span_id}?as_of={self.fixture.as_of.isoformat()}"
            span = self.http.request("GET", path, token).expect(200)
            verify_citation(citation, span, self.fixture, self.document_id, self.version_id)
            span_ids.append(span_id)
        self.report["fixture"]["span_ids"] = sorted(set(span_ids))

    def temporal_and_scope_denials(self, token: str) -> None:
        answer = self.http.request(
            "POST", "/v1/answers", token, self.fixture.query(before=True)
        ).expect(200)
        require_abstention(answer)
        for span_id in self.report["fixture"]["span_ids"]:
            self.http.request(
                "GET", f"/v1/spans/{span_id}?as_of={self.fixture.before}", token
            ).expect(404)
        unavailable = f"unassigned-{uuid4().hex}"
        request = {**self.fixture.query(), "corpus_ids": [unavailable]}
        denied = self.http.request("POST", "/v1/answers", token, request).expect(403)
        detail = object_payload(object_payload(denied).get("detail"))
        require(detail.get("reason") == "requested_corpora_not_held", "wrong scope denial reason")
        require(
            detail.get("denied_corpora") == [unavailable], "scope denial omitted requested corpus"
        )

    def outsider_denial(self) -> None:
        if self.credentials.outsider is None:
            self.report["outsider_scope_verified"] = False
            return
        self.stage = "outsider_source_denial"
        identity = object_payload(self.bootstrap(self.credentials.outsider).get("identity"))
        corpora = identity.get("corpora")
        require(
            isinstance(corpora, list) and self.fixture.corpus_id not in corpora,
            "outsider must not hold the smoke corpus",
        )
        self.http.request(
            "POST", "/v1/answers", self.credentials.outsider, self.fixture.query()
        ).expect(403)
        for span_id in self.report["fixture"]["span_ids"]:
            self.http.request("GET", f"/v1/spans/{span_id}", self.credentials.outsider).expect(404)
        self.report["outsider_scope_verified"] = True
        self.passed()


def credentials_from_arguments(args: argparse.Namespace) -> Credentials:
    owner = read_credential(args.owner_credential)
    reviewers = tuple(
        read_credential(reference) if reference else owner
        for reference in (
            args.metadata_credential,
            args.content_credential,
            args.approver_credential,
        )
    )
    return Credentials(
        owner,
        tuple(read_credential(value) for value in args.reader_credential),
        (reviewers[0], reviewers[1], reviewers[2]),
        read_credential(args.outsider_credential) if args.outsider_credential else None,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--base-url", required=True, help="API origin or browser origin with /api")
    result.add_argument("--corpus-id", required=True, help="dedicated pilot-smoke-<name> corpus")
    result.add_argument(
        "--exercise-fixture", action="store_true", help="authorize synthetic upload and review"
    )
    result.add_argument(
        "--owner-credential", required=True, help="env:NAME or file:PATH; never a token value"
    )
    result.add_argument(
        "--reader-credential", action="append", required=True, help="repeat 3–5 times"
    )
    result.add_argument("--metadata-credential", help="defaults to owner credential")
    result.add_argument("--content-credential", help="defaults to owner credential")
    result.add_argument("--approver-credential", help="defaults to owner credential")
    result.add_argument("--outsider-credential", help="optional read identity without smoke corpus")
    result.add_argument("--timeout", type=float, default=15.0)
    result.add_argument("--job-timeout", type=float, default=60.0)
    result.add_argument("--out", type=Path, default=Path("var/pilot-acceptance.json"))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        credentials = credentials_from_arguments(args)
        options = Options(
            args.base_url, args.corpus_id, args.exercise_fixture, args.timeout, args.job_timeout
        )
        report = PilotAcceptance(options, credentials).run()
    except ProbeFailure as exc:
        report = {
            "schema": "korpus.live-pilot-acceptance.v1",
            "status": "FAIL",
            "failed_check": "credentials",
            "failure": str(exc),
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    except OSError:
        print(json.dumps({"status": "FAIL", "failure": "acceptance report could not be saved"}))
        return 1
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
