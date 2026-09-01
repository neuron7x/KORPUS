import {call} from "./api.js";
import {PACK_STATE, createEd25519Verifier, validateOfflinePack} from "./offline_pack.js";
import {createOfflinePackStore} from "./offline_store.js";

export function createOfflineController({getIdentity, store = createOfflinePackStore(), apiCall = call, config = () => globalThis.window?.KORPUS_CONFIG ?? {}}) {
  async function validation(pack) {
    if (!pack) return Object.freeze({state: PACK_STATE.ABSENT, reason: "pack absent"});
    const identity = getIdentity?.();
    const cfg = config();
    if (!cfg.offlinePackPublicKeyB64 || !cfg.offlinePackKeyId) {
      return Object.freeze({state: PACK_STATE.CORRUPT, reason: "offline trust root is not provisioned"});
    }
    try {
      const verifySignature = await createEd25519Verifier(cfg.offlinePackPublicKeyB64);
      return validateOfflinePack(pack, {
        expectedCorpora: identity?.corpora ?? [],
        expectedKeyId: cfg.offlinePackKeyId,
        verifySignature,
      });
    } catch (error) {
      return Object.freeze({state: PACK_STATE.CORRUPT, reason: String(error?.message ?? error)});
    }
  }

  return Object.freeze({
    async state() {
      try { return validation(await store.load()); }
      catch (error) { return Object.freeze({state: PACK_STATE.CORRUPT, reason: String(error?.message ?? error)}); }
    },
    async exportFresh() {
      const identity = getIdentity?.();
      if (!identity) throw new Error("authenticated identity required for offline export");
      const pack = await apiCall("/v1/offline-pack", {method: "POST", body: {corpora: identity.corpora ?? []}});
      const result = await validation(pack);
      if (result.state !== PACK_STATE.VALID) throw new Error(`exported offline pack rejected: ${result.reason}`);
      await store.save(pack);
      return result;
    },
    async clear() { await store.clear(); },
  });
}
