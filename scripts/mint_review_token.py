#!/usr/bin/env python3
"""Mint a short-lived bearer token for a review session.

Not a production path and not a login: it exists so a demonstration can be shown to
people who are not at this keyboard, without putting dev authentication on a network.
`auth_mode=dev` trusts whoever connects and is refused on any non-loopback bind for
exactly that reason (`config.py`), so a review over a LAN has to carry a signed token.

In `auth_mode=jwt` the token *carries* the entitlements — `_identity_from_local_claims`
reads roles, clearance, corpora and compartments straight from the claims. The
server-side entitlement profile projects identity only in `auth_mode=oidc`, which is
what `controlled_requirements.py` forces in a controlled environment. So whoever holds
this token holds exactly what is written in it, and that is why it is short-lived, why
the secret is mode 600, and why this script refuses to mint anything above the corpora
it was told to.

Saying that plainly matters more than the convenience: a comment claiming the profile
constrains this token would be false, and a wrong sentence about an authorization
boundary is the thing this repository exists to refuse.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

#: Short by design. A review is a session someone sits through, not a credential that
#: outlives the room it was shown in.
DEFAULT_MINUTES = 120


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True)
    parser.add_argument("--minutes", type=int, default=DEFAULT_MINUTES)
    parser.add_argument("--issuer", default=os.environ.get("KORPUS_JWT_ISSUER", "korpus-local"))
    parser.add_argument("--audience", default=os.environ.get("KORPUS_JWT_AUDIENCE", "korpus-api"))
    parser.add_argument("--roles", default="user")
    parser.add_argument("--clearance", default="public")
    parser.add_argument("--corpora", default="public")
    arguments = parser.parse_args()

    secret = os.environ.get("KORPUS_JWT_SECRET", "")
    if len(secret) < 32:
        raise SystemExit("KORPUS_JWT_SECRET must be set and at least 32 characters")
    if arguments.minutes < 1 or arguments.minutes > 720:
        raise SystemExit("--minutes must be between 1 and 720")

    now = datetime.now(UTC)
    claims = {
        "sub": arguments.subject,
        "iss": arguments.issuer,
        "aud": arguments.audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=arguments.minutes)).timestamp()),
        "jti": str(uuid4()),
        # Carried, not projected — see the module docstring. Compartments are
        # deliberately absent: a review token must not reach compartmented material,
        # and the way to be sure is not to be able to ask for it here.
        "roles": sorted({role.strip() for role in arguments.roles.split(",") if role.strip()}),
        "clearance": arguments.clearance,
        "corpora": sorted({name.strip() for name in arguments.corpora.split(",") if name.strip()}),
    }
    print(jwt.encode(claims, secret, algorithm="HS256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
