# KORPUS v0.9.4 — Military Knowledge Iteration 2

## Implemented

1. Fail-closed Ed25519 offline-pack verification: digest, signature, schema, issuance/freshness and revocation are checked before a pack becomes usable.
2. Audience-level explanation envelope: recruit/operator/NCO/officer/instructor presentation can vary while exact claim IDs and evidence bindings must remain invariant.
3. Human correction review queue: reports are deterministic and deduplicated; user feedback never mutates corpus truth automatically.
4. Bounded effective knowledge-graph traversal: expired relations are excluded and traversal depth is hard bounded.
5. Immutable effective graph index for repeated same-date navigation with exact equivalence against direct traversal.

## Verification

- Focused military/learning/offline suite: PASS.
- Broader retrieval/evidence/authority/access/policy suite: PASS.
- Precomputed graph index equivalence: exact across tested depths 0..7.
- Source manifest: regenerated and verified after changes.
- CURRENT_TRUTH remains fail-closed because prior evidence reports are bound to an older source digest; no evidence report was relabeled without re-execution.

## Performance evidence

Synthetic graph: 5,000 nodes / 4,999 edges, 1,000 depth-4 traversals.

- direct traversal: ~2.91 s
- index construction: ~0.0143 s
- indexed traversal: ~0.00362 s / 1,000 queries
- repeated-query speedup after index construction: ~804x
- break-even: ~5 repeated queries

Correction queue benchmark: 20,000 submissions -> 200 deterministic review items in ~0.030 s (~669k submissions/s on audit host).

These measurements are microbenchmarks, not production SLO evidence.

## 2026 engineering alignment

- NATO Alliance Digital Strategy: role-appropriate digital proficiency, responsible interaction with AI-enabled systems, trusted data-driven decision support and tactical-edge capability.
- NATO JADL: structured LMS-based military learning and continuing training.
- OpenAI 2026 evaluation practice: claims, tested harness, resource budgets and validity checks must be explicit; benchmark results do not imply broader production claims.
- OWASP GenAI Data Security 2026: data-layer controls, validation, monitoring and AI-specific security testing are lifecycle requirements.

## Next execution block

1. API integration for graph navigation and doctrine revision diff.
2. Persisted assessment attempts, mastery state and prerequisite-aware learning progression.
3. Offline pack verification endpoint/client contract and trusted key rotation/revocation metadata.
4. Source-change invalidation: changed doctrine automatically invalidates dependent lessons/checks without deleting history.
5. Real-domain military TEVV protocol and blinded SME adjudication schema.
6. Load/soak benchmark for retrieval + evidence + graph + offline pathways.
