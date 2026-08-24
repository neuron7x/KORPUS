import test from "node:test";
import assert from "node:assert/strict";
import {ROUTES, resolveRoute, routeAccess, routeHref, routeState} from "../public/routes.js";

const required=["/login","/chat","/knowledge","/documents","/sources","/offline","/audit","/profile","/access-denied"];
test("MUDR functional routes are canonical and unique",()=>{
  assert.deepEqual(ROUTES.map(route=>route.path),required);
  assert.equal(new Set(ROUTES.map(route=>route.path)).size,required.length);
});
test("deep links and conversation links round trip",()=>{
  for(const path of required) assert.equal(resolveRoute(path)?.path,path);
  const href=routeHref("chat-conversation",{conversationId:"abc-123"});
  assert.equal(href,"/chat/abc-123");
  assert.equal(resolveRoute(href)?.params.conversationId,"abc-123");
});
test("hostile or malformed conversation identifiers do not become routes",()=>{
  for(const path of ["/chat/%0aevil","/chat/a%2Fb","/chat/<script>","/unknown"]) assert.equal(resolveRoute(path),null);
});
test("authenticated routes require server-projected permissions and capabilities",()=>{
  const bootstrap={effective_permissions:["audit:read","answer:read"],capabilities:{offline_pack_enabled:false}};
  assert.deepEqual(routeAccess(resolveRoute("/audit"),false,bootstrap),{allowed:false,redirect:"/login"});
  assert.deepEqual(routeAccess(resolveRoute("/audit"),true,bootstrap),{allowed:true,redirect:null});
  assert.deepEqual(routeAccess(resolveRoute("/documents"),true,bootstrap),{allowed:false,redirect:"/access-denied"});
  assert.deepEqual(routeAccess(resolveRoute("/offline"),true,bootstrap),{allowed:false,redirect:"/access-denied"});
});
test("every route view state is explicit and errors require a reason",()=>{
  for(const state of ["loading","empty","success"]) assert.equal(routeState(state).kind,state);
  assert.equal(routeState("error","boom").kind,"error");
  assert.throws(()=>routeState("error"));
});
