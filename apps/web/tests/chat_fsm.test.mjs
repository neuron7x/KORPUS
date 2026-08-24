import test from "node:test";
import assert from "node:assert/strict";
import {CHAT_STATE, createChatMachine, replayServerOutcome, serverOutcome, transition} from "../public/chat_fsm.js";

test("happy evidence path reaches COMPLETE through explicit audit commit", () => {
  const m = createChatMachine(CHAT_STATE.READY);
  m.send("SUBMIT"); m.send("REQUEST_SENT");
  replayServerOutcome(m, {status:"answered", decision_reason:"ok", citations:[{span_id:"s"}]});
  assert.equal(m.state, CHAT_STATE.COMPLETE);
  assert.deepEqual(m.history.slice(-5), ["RETRIEVING","EVIDENCE_FOUND","ANSWER_READY","AUDIT_COMMIT","COMPLETE"]);
});

test("no evidence and conflict cannot become ANSWER_READY", () => {
  for (const answer of [
    {status:"abstained", decision_reason:"retrieval_gate_failed", citations:[]},
    {status:"requires_human_review", decision_reason:"contradictory_authoritative_evidence", citations:[{span_id:"s"}]},
  ]) {
    const m=createChatMachine(CHAT_STATE.READY); m.send("SUBMIT"); m.send("REQUEST_SENT"); replayServerOutcome(m, answer);
    assert.equal(m.state, CHAT_STATE.COMPLETE);
    assert.ok(!m.history.includes(CHAT_STATE.ANSWER_READY));
  }
});

test("malformed answered response fails closed instead of treating text as evidence", () => {
  assert.equal(serverOutcome({status:"answered", citations:[]}), "FAIL");
  const m=createChatMachine(CHAT_STATE.READY); m.send("SUBMIT"); m.send("REQUEST_SENT"); replayServerOutcome(m,{status:"answered",citations:[]});
  assert.equal(m.state, CHAT_STATE.FAIL_CLOSED);
});

test("invalid transitions are rejected, not ignored", () => {
  assert.throws(()=>transition(CHAT_STATE.READY,"AUDIT_OK"),/invalid chat transition/);
});
