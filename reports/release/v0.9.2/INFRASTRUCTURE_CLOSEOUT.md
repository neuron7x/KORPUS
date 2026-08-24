# KORPUS v0.9.2 Infrastructure Closeout

Status: **PASS_WITH_CAVEATS**. Production authorization: **false**.

## Verified local state

- GCP-focused tests: **116/116 PASS**, failures **0**, errors **0**, skipped **0**.
- GCP production predicates: **72/72 PASS**.
- Terraform structural validation: **23/23 `.tf` files**, **0 findings**.
- Infrastructure requirements: **135/135 PASS**.
- GitHub Actions policy: **7 workflows**, **0 findings**.
- Module ratchet: **325 modules**, **0 violations**.
- Canonical source manifest: **973 files**, SHA-256 root `4fa3f5a6b015f56bafe8127880bee48d65ec6b3b9229b7a81d111f9244f81bd7`.
- Production hard predicates: **12/12 software-ready; 0/12 externally satisfied**.

## P0 correction

v0.9.1 overstated the Cloud SQL private-network state. v0.9.2 fixes the actual Terraform: dedicated VPC/subnet, Private Service Access, `ipv4_enabled=false`, `private_network` binding, and Direct VPC egress for API, worker, migrator and verifier. Mutation predicates kill public-IP/PSA/VPC-bypass regressions.

## Promotion semantics

Upgrade path is fail-closed: 0%-traffic candidate → exact tagged private probe → bounded canary → revision-specific successful-2xx sample and 5xx-rate gate → 100% promotion; any downstream failure invokes revision-exact rollback.

## External boundary

Local provider-schema `terraform init/validate` was not executed because the sandbox could not resolve HashiCorp distribution endpoints. No live authenticated GCP apply, live production traffic evidence, external independent red-team/TEVV, or real-domain corpus TEVV was executed.
