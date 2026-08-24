import test from "node:test";
import assert from "node:assert/strict";
import {PACK_STATE, canonicalPackPayload, createEd25519Verifier, offlineAnswerPermitted, sha256Hex, validateOfflinePack} from "../public/offline_pack.js";

async function fixture(overrides={}) {
  const base={schema:"korpus.offline-pack.v1",algorithm:"Ed25519",key_id:"k1",pack_id:"p1",corpus_release:"r1",corpora:["public"],valid_until:"2026-08-20T00:00:00Z",revoked:false,signature:"fixture-signature"};
  const withoutDigest={...base,...overrides};
  const raw=canonicalPackPayload({...withoutDigest,payload_sha256:"0".repeat(64)}).replace(/,"payload_sha256":"[a-f0-9]{64}"/,"");
  return {...withoutDigest,payload_sha256:await sha256Hex(raw)};
}
const verifier=async()=>true;

test("only cryptographically accepted, current, scoped pack may answer",async()=>{
  const valid=await validateOfflinePack(await fixture(),{now:"2026-08-16T00:00:00Z",expectedCorpora:["public"],verifySignature:verifier});
  assert.equal(valid.state,PACK_STATE.VALID); assert.equal(offlineAnswerPermitted(valid),true);
  const stale=await validateOfflinePack(await fixture(),{now:"2026-08-21T00:00:00Z",expectedCorpora:["public"],verifySignature:verifier});
  assert.equal(stale.state,PACK_STATE.STALE); assert.equal(offlineAnswerPermitted(stale),false);
  const revoked=await validateOfflinePack(await fixture({revoked:true}),{now:"2026-08-16T00:00:00Z",expectedCorpora:["public"],verifySignature:verifier});
  assert.equal(revoked.state,PACK_STATE.REVOKED);
  const scope=await validateOfflinePack(await fixture(),{now:"2026-08-16T00:00:00Z",expectedCorpora:["restricted"],verifySignature:verifier});
  assert.equal(scope.state,PACK_STATE.SCOPE_MISMATCH);
});

test("digest or signature tamper fails closed as CORRUPT",async()=>{
  const pack=await fixture(); pack.corpora=["public","secret"];
  const tamper=await validateOfflinePack(pack,{now:"2026-08-16T00:00:00Z",verifySignature:verifier});
  assert.equal(tamper.state,PACK_STATE.CORRUPT);
  const rejected=await validateOfflinePack(await fixture(),{now:"2026-08-16T00:00:00Z",verifySignature:async()=>false});
  assert.equal(rejected.state,PACK_STATE.CORRUPT);
});

test("a verifier is mandatory and never taken from the pack itself",async()=>{
  const pack=await fixture();
  await assert.rejects(()=>validateOfflinePack(pack,{now:"2026-08-16T00:00:00Z"}),/trusted signature verifier required/);
});

function b64(bytes){return Buffer.from(bytes).toString("base64");}

test("the production Ed25519 verifier accepts only the pinned key and exact payload",async()=>{
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const publicRaw=await crypto.subtle.exportKey("raw",pair.publicKey);
  const pack=await fixture();
  const material=canonicalPackPayload(pack);
  pack.signature=b64(await crypto.subtle.sign({name:"Ed25519"},pair.privateKey,new TextEncoder().encode(material)));
  const verifySignature=await createEd25519Verifier(b64(publicRaw));
  const accepted=await validateOfflinePack(pack,{now:"2026-08-16T00:00:00Z",expectedCorpora:["public"],expectedKeyId:"k1",verifySignature});
  assert.equal(accepted.state,PACK_STATE.VALID);
  const wrongKey=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const wrongRaw=await crypto.subtle.exportKey("raw",wrongKey.publicKey);
  const wrongVerifier=await createEd25519Verifier(b64(wrongRaw));
  const rejected=await validateOfflinePack(pack,{now:"2026-08-16T00:00:00Z",expectedKeyId:"k1",verifySignature:wrongVerifier});
  assert.equal(rejected.state,PACK_STATE.CORRUPT);
});
