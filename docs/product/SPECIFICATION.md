# Product specification

Status: baseline v0.1 · Date: 2026-07-31 · Owner: product partners

## Theme

An evidence-first Ukrainian knowledge, training, and administrative-assistance
platform for service members and instructors.

## Mission

Reduce time spent searching fragmented documents and group chats while increasing
the traceability, currency, and honest uncertainty of answers.

## Problem

The target user has a real question but faces one or more failure modes:

- the answer is distributed across large, inconsistently organized collections;
- a domain expert is not online;
- a general chatbot produces fluent but unsupported text;
- the applicable edition, role, platform, or authority is unclear;
- administrative documents are returned for correction;
- training materials exist but are not assembled into a measurable path.

## Target outcomes

1. A user reaches an applicable source in under 60 seconds.
2. Every supported answer exposes claim-level citations.
3. Unsupported questions abstain instead of guessing.
4. An instructor can compose a reviewed lesson plan and assessment.
5. A user can produce a clearly marked administrative draft from an approved template.
6. Corpus owners can trace every answer to immutable source versions.

## Users and jobs

| Persona | Job to be done | Guardrail |
|---|---|---|
| Learner | Find and understand an approved source | No implied qualification |
| Instructor | Build lessons, quizzes, and progress checks | Human approves curriculum |
| Specialist | Resolve a narrow reference question | Role/platform filters required |
| Administrator | Draft a routine document | Draft is not an official submission |
| Reviewer | Approve, supersede, or reject sources | Four-eyes rule for high-risk corpora |
| Auditor | Reconstruct why an answer was shown | Immutable event and evidence IDs |

## MVP scope

- authenticated PWA and responsive web;
- corpus browsing and hybrid retrieval;
- evidence-bound Q&A with abstention and citations;
- source metadata, revision, and approval workflow;
- instructor curriculum builder and quiz drafts;
- administrative document drafts from versioned templates;
- feedback, incident reporting, and evaluation telemetry;
- Ukrainian-first UX with English source support.

## Explicitly out of scope for MVP

- autonomous operational decisions or targeting;
- real-time command and control;
- publishing restricted manuals to general users;
- medical diagnosis or treatment decisions;
- unreviewed explosive, diversionary, interrogation, or other high-risk instructions;
- automatic submission/signing of official documents;
- claims that the system is error-free.

## Core services

### Evidence Q&A

Input: question, user role/tier, selected corpus, locale. Output: answer status,
claims, citations, confidence, limitations, and feedback hook.

### Learning

Creates a competency path from approved learning objectives. Generates question
drafts, but promotion to an active exam requires reviewer approval. Scores knowledge,
not real-world qualification.

### Document assistance

Selects a versioned template, asks for missing fields, validates required data, and
produces an editable draft plus the governing source. It never fabricates identifiers.

### Corpus operations

Ingest, malware-scan, fingerprint, OCR, classify, deduplicate, review, approve,
supersede, revoke, reindex, and audit documents.

## Success metrics

- retrieval Recall@10 ≥ 0.90 on the frozen domain eval set;
- MRR@10 ≥ 0.80 for single-source questions;
- citation precision ≥ 0.95;
- citation coverage ≥ 0.95 of verifiable answer claims;
- unsupported-question abstention recall ≥ 0.95;
- cross-tier access leakage = 0 in automated adversarial tests;
- p95 retrieval latency < 1.5 s and streamed first-token latency < 3 s under target load;
- template validation catches 100% of required-field omissions in fixtures.

Metrics are release gates, not marketing claims; thresholds may change only by ADR.

