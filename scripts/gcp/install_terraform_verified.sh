#!/usr/bin/env bash
set -euo pipefail

readonly TERRAFORM_VERSION="${TERRAFORM_VERSION:-1.15.8}"
readonly HASHICORP_RELEASE_FINGERPRINT="C874011F0AB405110D02105534365D9472D7468F"
readonly HASHICORP_SIGNING_KEY_URL="https://www.hashicorp.com/.well-known/pgp-key.txt"
readonly RELEASE_ROOT="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}"
readonly INSTALL_DIR="${INSTALL_DIR:-${HOME}/.local/bin}"

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "required command missing: $1" >&2; exit 2; }
}
for cmd in curl gpg sha256sum unzip awk tr mktemp install; do require "$cmd"; done

case "$(uname -s)" in
  Linux) os="linux" ;;
  Darwin) os="darwin" ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac

archive="terraform_${TERRAFORM_VERSION}_${os}_${arch}.zip"
sums="terraform_${TERRAFORM_VERSION}_SHA256SUMS"
sig="${sums}.72D7468F.sig"
work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT
export GNUPGHOME="$work/gnupg"
mkdir -m 700 "$GNUPGHOME"

curl --proto '=https' --tlsv1.2 --fail --show-error --silent --location \
  "$HASHICORP_SIGNING_KEY_URL" -o "$work/hashicorp.asc"
for file in "$archive" "$sums" "$sig"; do
  curl --proto '=https' --tlsv1.2 --fail --show-error --silent --location \
    "$RELEASE_ROOT/$file" -o "$work/$file"
done

gpg --batch --import "$work/hashicorp.asc" >/dev/null 2>&1
fingerprint="$(gpg --batch --with-colons --fingerprint 72D7468F | awk -F: '$1=="fpr" {print $10; exit}')"
if [[ "$fingerprint" != "$HASHICORP_RELEASE_FINGERPRINT" ]]; then
  echo "HashiCorp signing-key fingerprint mismatch" >&2
  exit 3
fi

gpg --batch --verify "$work/$sig" "$work/$sums" >/dev/null 2>&1
(
  cd "$work"
  expected_line="$(awk -v a="$archive" '$2 == a {print; found=1} END {if (!found) exit 1}' "$sums")"
  printf '%s\n' "$expected_line" | sha256sum --check --strict -
)

mkdir -p "$INSTALL_DIR"
unzip -p "$work/$archive" terraform > "$work/terraform"
install -m 0755 "$work/terraform" "$INSTALL_DIR/terraform"
"$INSTALL_DIR/terraform" version
