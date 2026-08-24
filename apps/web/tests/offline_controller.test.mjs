import test from "node:test";
import assert from "node:assert/strict";
import {createOfflineController} from "../public/offline_controller.js";
import {canonicalPackPayload, sha256Hex} from "../public/offline_pack.js";

function b64(bytes){return Buffer.from(bytes).toString("base64");}

async function signedPack(pair){
  const base={schema:"korpus.offline-pack.v1",algorithm:"Ed25519",key_id:"k1",subject:"reader",corpus_release:"r1",corpora:["public"],valid_until:"2099-01-01T00:00:00Z",revoked:false,spans:[]};
  const probe=canonicalPackPayload({...base,payload_sha256:"0".repeat(64),signature:"x"}).replace(/,"payload_sha256":"[a-f0-9]{64}"/,"");
  const withDigest={...base,payload_sha256:await sha256Hex(probe)};
  const material=canonicalPackPayload({...withDigest,signature:"x"});
  return {...withDigest,signature:b64(await crypto.subtle.sign({name:"Ed25519"},pair.privateKey,new TextEncoder().encode(material)))};
}

test("fresh export is persisted only after pinned-key validation",async()=>{
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const pub=b64(await crypto.subtle.exportKey("raw",pair.publicKey));
  const pack=await signedPack(pair);
  let stored=null;
  const store={load:async()=>stored,save:async value=>{stored=value;},clear:async()=>{stored=null;}};
  const controller=createOfflineController({
    getIdentity:()=>({corpora:["public"]}),store,
    apiCall:async()=>pack,
    config:()=>({offlinePackPublicKeyB64:pub,offlinePackKeyId:"k1"}),
  });
  const result=await controller.exportFresh();
  assert.equal(result.state,"PACK_VALID");
  assert.equal(stored.payload_sha256,pack.payload_sha256);
});

test("missing trust root refuses persistence",async()=>{
  let saved=false;
  const store={load:async()=>null,save:async()=>{saved=true;},clear:async()=>{}};
  const controller=createOfflineController({
    getIdentity:()=>({corpora:["public"]}),store,
    apiCall:async()=>({}),config:()=>({}),
  });
  await assert.rejects(()=>controller.exportFresh(),/rejected/);
  assert.equal(saved,false);
});
