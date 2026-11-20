# Private laptop pilot

The first usable scope is one owner, one narrow corpus and three to five invited
readers. The canonical Compose stack serves the browser through Nginx at
`http://127.0.0.1:3000`; its API uses PostgreSQL, MinIO, ClamAV and the durable worker.
Local JWT sessions are short lived and manually issued. They provide a private
pilot session, not an invitation/password-management product.

## Qualify a disposable stack first

Requirements: Python 3.12, the locked API dependencies, Docker Engine/Desktop with
a local Unix socket and Compose v2, and a free loopback port 3000. The runner
refuses explicit `DOCKER_HOST`/`DOCKER_CONTEXT`/TLS endpoint overrides and a remote
Docker context. It never changes Docker configuration or stops another service.
An explicit `DOCKER_CONFIG` directory is preserved for CLI context and registry
credential selection; neither its contents nor registry credentials enter containers.

```sh
make api-install
make compose-pilot-smoke
```

The command builds the pinned stack in a fresh random project, generates synthetic
secrets in a private temporary directory, enables review separation, and runs
`run_pilot_acceptance.py` against `http://127.0.0.1:3000/api`. Five distinct readers,
three separate reviewers and an outsider exercise a neutral archive-color fixture.
It also checks Nginx readiness with the configured exact hostname and rejects an
unassigned hostname. `infra/secrets`, application credentials and operator `.env` files
are not used or modified. Container images may use the ordinary build cache;
database, object-store, scanner and audit volumes are new for every run.
The two read-only infrastructure configuration files are copied byte for byte into
private state and given the existing generator's container-readable file modes.
The probe pauses 250 ms after each completed stage; it does not change rate limits
or retry failed write requests.

Exit zero requires the real durable upload, all review transitions, grounded
answers, exact source disclosure and access denials to pass, followed by successful
removal of that project's containers, networks and volumes. Cleanup uses only the
owned random project and refuses changed ownership/configuration. No global prune
or unqualified `down -v` is used. If cleanup fails, the report names the random
project and retained private state for operator recovery; the run fails.

Read `var/compose-pilot-smoke.json`. The same command runs in
`.github/workflows/compose-pilot-smoke.yml`; only the sanitized report is uploaded.
It contains no tokens, signing secrets or raw service logs. A missing Docker daemon
is a failure, not a successful or skipped qualification.

This establishes the measured **Compose and authenticated HTTP journey**. It does
not prove deployment on the owner's computer, external HTTPS, browser interaction,
load capacity, recovery or answer quality on the owner's documents.

## Start the owner's stack

Use a reviewed merged revision, then create persistent operator secrets and build:

```sh
make infra-secrets
docker compose up -d --build --wait --wait-timeout 600 web worker
curl --fail --silent --show-error http://127.0.0.1:3000/healthz
curl --fail --silent --show-error http://127.0.0.1:3000/api/ready
```

Keep the generated secrets and named volumes. `docker compose down` stops the stack
without deleting volumes; the disposable smoke's volume cleanup is not an operator
shutdown command. First-time image and scanner startup must complete before upload.

## Use an exact private HTTPS hostname

The base Compose file hardcodes loopback trusted hosts and CORS origins. Merely
exporting those `KORPUS_*` variables does not override it. Use the supplied overlay
with a hostname whose DNS and HTTPS route the operator controls:

```sh
export PILOT_HOSTNAME='your-real-pilot-hostname'
case "$PILOT_HOSTNAME" in
  ''|*[!A-Za-z0-9.-]*|.*|*.) printf '%s\n' 'Use one exact DNS hostname, without scheme, port, wildcard or list.' >&2; exit 1 ;;
esac
dc() {
  docker compose -f docker-compose.yml -f deploy/pilot/compose.private.yaml "$@"
}
dc config --quiet
dc up -d --build --wait --wait-timeout 600 web worker
```

Compose refuses a missing hostname; the shell check above rejects wildcard/list
input. There is no wildcard or anonymous-auth default. Persist
the value in the operator's private shell/environment configuration for subsequent
commands. The overlay preserves JWT and the single `127.0.0.1:3000` publication;
PostgreSQL, MinIO and the API remain unpublished.

A stable HTTPS reverse proxy or named tunnel on that computer must forward the
exact Host to `http://127.0.0.1:3000`. Provisioning its DNS/TLS/account requires the
actual host and provider. The existing rotating public tunnel and development web
server do not establish this private HTTPS route. Test from a reader's device.
Browser OIDC is a separate setup, including correct proxy scheme handling.

## Issue scoped owner and reader sessions

Create private files on the operator's computer, outside the checkout:

```sh
PILOT_STATE="$HOME/.local/state/korpus-pilot"
mkdir -p "$PILOT_STATE"
chmod 700 "$PILOT_STATE"
umask 077
dc exec -T api /usr/local/bin/korpus-entrypoint \
  python /app/scripts/mint_review_token.py \
  --subject owner --roles curator,reviewer,user \
  --clearance authenticated --corpora pilot --minutes 120 \
  > "$PILOT_STATE/owner.token"
for reader in 1 2 3; do
  dc exec -T api /usr/local/bin/korpus-entrypoint \
    python /app/scripts/mint_review_token.py \
    --subject "reader-$reader" --roles user \
    --clearance authenticated --corpora pilot --minutes 120 \
    > "$PILOT_STATE/reader-$reader.token"
done
```

Use stable distinct subjects for the actual people. Give each reader only their own
token through an appropriate private channel; never put it in the URL. Explicitly
running the entrypoint matters: ordinary `docker compose exec ... python` does not
inherit secrets exported by the container's startup process. The browser stores a
bearer only in the current tab's memory. Expiry or a new tab requires a new session
entry; this path does not implement invitation, password reset or persistent login.

## Upload, review and ask

1. Open `/console.html`, enter the owner token in the bearer section and verify it.
2. Set corpus `pilot` explicitly; the form initially shows `public`. Supply truthful
   title, issuer, revision, authority, publication/effective date and access tier.
3. Preview the upload, submit it, and wait for the durable job to succeed. Record
   the resulting version ID. Quarantined sources cannot answer reader questions.
4. Perform `metadata_reviewed`, `content_reviewed`, then `approved`, with a reason
   for each transition. If the configured review-separation policy requires
   different people, use their distinct credentials; keep that policy intact.
5. Open the main page as a reader, verify the reader token, ask a known question,
   and open its cited source fragment. The three readers must receive answers
   within their assigned corpus and no writing permission.

Default planner/composer assistance remains disabled; the extractive answer path
does not require a model API key. Do not infer generative answer quality from a
successful extractive fixture answer.

For a repeatable live check through the reader-facing origin, use
[PILOT_ACCEPTANCE.md](PILOT_ACCEPTANCE.md) with `--base-url https://HOST/api` and
separate credentials for a fresh `pilot-smoke-*` corpus. Keep that synthetic scope
separate from the owner's documents. The qualification runner creates and destroys
its own isolated stack; the live probe deliberately retains its audit evidence.

## Persistence and recovery boundary

The named PostgreSQL, MinIO and audit-anchor volumes survive an ordinary restart.
That is not a backup. The existing encrypted PostgreSQL backup and restore commands
are documented in [BACKUP_RESTORE.md](../runbooks/BACKUP_RESTORE.md); the host needs
a PostgreSQL client/connection path or an explicit container adapter. Database
backup alone does not preserve MinIO source objects or the independent audit anchor.
A complete restore drill for all three components and a known cited answer remains
required before claiming recoverability of the owner's pilot.
