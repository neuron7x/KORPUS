# Initial risk register

| ID | Risk | Likelihood | Impact | Owner | Treatment |
|---|---|---:|---:|---|---|
| R-01 | Unsupported answer trusted as fact | High | Critical | AI quality | Evidence gate, abstention, evals |
| R-02 | Restricted data reaches public route | Medium | Critical | Security | ABAC, store isolation, leakage tests |
| R-03 | Purchased file lacks reuse rights | Medium | High | Corpus steward | Rights review before approval |
| R-04 | Superseded rule remains searchable | High | High | Corpus steward | Validity graph, revalidation jobs |
| R-05 | Prompt injection from corpus | High | High | Security | Untrusted-content boundary, tool denial |
| R-06 | Medical guidance used outside role | Medium | Critical | Medical reviewer | Role gates, reviewed scopes, disclaimers |
| R-07 | Provider outage blocks access | Medium | Medium | Reliability | Browse-only degraded mode, adapter fallback |
| R-08 | Costs grow with PDFs/long context | High | Medium | Engineering | extraction/RAG, routing, token budgets |
| R-09 | Weak network makes app unusable | High | High | Web | PWA shell, resumable calls, compact payloads |
| R-10 | Metrics optimized without user value | Medium | Medium | Product | task outcomes and field validation |

