// Offline packs are data plus an external signature decision. This module does not
// contain a demo secret and cannot self-sign. Production must inject a verifier whose
// trust root is provisioned outside the pack being checked.

export const PACK_STATE = Object.freeze({
  ABSENT: "PACK_ABSENT",
  VALIDATING: "PACK_VALIDATING",
  VALID: "PACK_VALID",
  STALE: "PACK_STALE",
  REVOKED: "PACK_REVOKED",
  CORRUPT: "PACK_CORRUPT",
  SCOPE_MISMATCH: "PACK_SCOPE_MISMATCH",
});

const HEX64 = /^[a-f0-9]{64}$/;

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function canonicalPackPayload(pack) {
  const {signature, ...payload} = pack ?? {};
  return canonical(payload);
}

export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function decodeBase64(value) {
  const raw = globalThis.atob(String(value ?? ""));
  return Uint8Array.from(raw, char => char.charCodeAt(0));
}

export async function createEd25519Verifier(publicKeyB64) {
  const raw = decodeBase64(publicKeyB64);
  if (raw.byteLength !== 32) throw new Error("Ed25519 public key must be 32 bytes");
  const key = await globalThis.crypto.subtle.importKey("raw", raw, {name: "Ed25519"}, false, ["verify"]);
  return async (material, signatureB64) => {
    let signature;
    try { signature = decodeBase64(signatureB64); } catch { return false; }
    return globalThis.crypto.subtle.verify(
      {name: "Ed25519"}, key, signature, new TextEncoder().encode(String(material)),
    );
  };
}

export async function validateOfflinePack(pack, context) {
  if (!pack) return Object.freeze({state: PACK_STATE.ABSENT, reason: "pack absent"});
  const now = context?.now instanceof Date ? context.now : new Date(context?.now ?? Date.now());
  if (Number.isNaN(now.getTime())) throw new Error("invalid validation clock");
  if (typeof context?.verifySignature !== "function") throw new Error("trusted signature verifier required");
  try {
    if (pack.schema !== "korpus.offline-pack.v1") throw new Error("unsupported pack schema");
    if (pack.algorithm !== "Ed25519") throw new Error("unsupported pack signature algorithm");
    if (context.expectedKeyId && pack.key_id !== context.expectedKeyId) throw new Error("offline pack key id mismatch");
    if (!Array.isArray(pack.corpora) || pack.corpora.length === 0) throw new Error("empty pack scope");
    if (!HEX64.test(String(pack.payload_sha256 ?? ""))) throw new Error("invalid payload digest");
    if (typeof pack.signature !== "string" || pack.signature.length < 16) throw new Error("missing signature");
    const material = canonicalPackPayload(pack);
    const digest = await sha256Hex(material.replace(/,"payload_sha256":"[a-f0-9]{64}"/, ""));
    // payload_sha256 commits the signed payload without the digest field itself; the
    // signature then commits the full canonical payload including that digest.
    if (digest !== pack.payload_sha256) throw new Error("payload digest mismatch");
    if (!(await context.verifySignature(material, pack.signature))) throw new Error("signature rejected");
  } catch (error) {
    return Object.freeze({state: PACK_STATE.CORRUPT, reason: String(error?.message ?? error)});
  }
  if (pack.revoked === true) return Object.freeze({state: PACK_STATE.REVOKED, reason: "pack revoked"});
  const expected = new Set(context.expectedCorpora ?? []);
  const actual = new Set(pack.corpora);
  if (expected.size && [...expected].some(item => !actual.has(item))) {
    return Object.freeze({state: PACK_STATE.SCOPE_MISMATCH, reason: "required corpus absent"});
  }
  const validUntil = new Date(pack.valid_until);
  if (Number.isNaN(validUntil.getTime())) return Object.freeze({state: PACK_STATE.CORRUPT, reason: "invalid expiry"});
  if (now > validUntil) return Object.freeze({state: PACK_STATE.STALE, reason: "pack expired"});
  return Object.freeze({state: PACK_STATE.VALID, reason: "signature, scope and validity accepted"});
}

export function offlineAnswerPermitted(validation) {
  return validation?.state === PACK_STATE.VALID;
}
