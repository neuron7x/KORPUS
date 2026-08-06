#!/usr/bin/env bash
# Keep a public HTTPS address pointed at the local edge, and write down where it is.
#
# The address is not durable and nothing here pretends otherwise: it is a free SSH
# reverse tunnel, the provider rotates the hostname on every reconnect, and it can drop.
# So the loop reconnects, and the current address is written to var/public/URL — one
# place to read rather than a log to grep.
#
# The file is emptied the moment the tunnel is gone rather than left holding the last
# address that worked. A stale link handed to somebody who needs an answer costs more
# than no link: they read "нема з'єднання" as "the system has nothing to say".
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${KORPUS_PUBLIC_EDGE_PORT:-8081}"
STATE="var/public"
mkdir -p "$STATE"

while true; do
  : > "$STATE/URL"
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -R "80:127.0.0.1:$PORT" nokey@localhost.run 2>&1 \
  | while IFS= read -r line; do
      printf '%s %s\n' "$(date -Is)" "$line" >> "$STATE/tunnel.log"
      address="$(printf '%s' "$line" | grep -oE 'https://[a-z0-9.-]+\.lhr\.life' | head -1)"
      if [[ -n "$address" ]]; then
        printf '%s\n' "$address" > "$STATE/URL"
        # One line per session, timestamped, so "how long does it hold" is a measurement
        # and not an impression. Without this the log records twelve addresses and no
        # way to tell a provider drop from a restart somebody performed by hand.
        printf '%s UP %s\n' "$(date -Is)" "$address" >> "$STATE/sessions.log"
        printf 'public address: %s\n' "$address"
      fi
    done
  printf '%s DOWN\n' "$(date -Is)" >> "$STATE/sessions.log"
  : > "$STATE/URL"
  sleep 5
done
