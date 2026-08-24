// Deterministic consumer-state machine. The browser never invents policy authority:
// server outcomes are mapped into visible states only after a response/refusal exists.

export const CHAT_STATE = Object.freeze({
  UNAUTHENTICATED: "UNAUTHENTICATED",
  AUTHENTICATING: "AUTHENTICATING",
  READY: "READY",
  QUERY_SUBMITTED: "QUERY_SUBMITTED",
  POLICY_CHECK: "POLICY_CHECK",
  ACCESS_DENIED: "ACCESS_DENIED",
  RETRIEVING: "RETRIEVING",
  NO_EVIDENCE: "NO_EVIDENCE",
  EVIDENCE_FOUND: "EVIDENCE_FOUND",
  CONFLICT: "CONFLICT",
  COMPOSING: "COMPOSING",
  ANSWER_READY: "ANSWER_READY",
  AUDIT_COMMIT: "AUDIT_COMMIT",
  COMPLETE: "COMPLETE",
  FAIL_CLOSED: "FAIL_CLOSED",
});

const TRANSITIONS = Object.freeze({
  UNAUTHENTICATED: {AUTH_BEGIN: "AUTHENTICATING"},
  AUTHENTICATING: {AUTH_OK: "READY", AUTH_FAIL: "UNAUTHENTICATED"},
  READY: {SUBMIT: "QUERY_SUBMITTED", LOGOUT: "UNAUTHENTICATED"},
  QUERY_SUBMITTED: {REQUEST_SENT: "POLICY_CHECK", CANCEL: "READY", FAIL: "FAIL_CLOSED"},
  POLICY_CHECK: {
    SERVER_DENIED: "ACCESS_DENIED",
    SERVER_SEARCHED: "RETRIEVING",
    CANCEL: "READY",
    FAIL: "FAIL_CLOSED",
  },
  ACCESS_DENIED: {AUDIT_OK: "COMPLETE", AUDIT_FAIL: "FAIL_CLOSED", RESET: "READY"},
  RETRIEVING: {
    SERVER_NO_EVIDENCE: "NO_EVIDENCE",
    SERVER_EVIDENCE: "EVIDENCE_FOUND",
    SERVER_CONFLICT: "CONFLICT",
    CANCEL: "READY",
    FAIL: "FAIL_CLOSED",
  },
  NO_EVIDENCE: {AUDIT_BEGIN: "AUDIT_COMMIT", FAIL: "FAIL_CLOSED"},
  EVIDENCE_FOUND: {COMPOSE_BEGIN: "COMPOSING", ANSWER_ACCEPTED: "ANSWER_READY", FAIL: "FAIL_CLOSED"},
  CONFLICT: {AUDIT_BEGIN: "AUDIT_COMMIT", FAIL: "FAIL_CLOSED"},
  COMPOSING: {ANSWER_ACCEPTED: "ANSWER_READY", FAIL: "FAIL_CLOSED"},
  ANSWER_READY: {AUDIT_BEGIN: "AUDIT_COMMIT", FAIL: "FAIL_CLOSED"},
  AUDIT_COMMIT: {AUDIT_OK: "COMPLETE", AUDIT_FAIL: "FAIL_CLOSED"},
  COMPLETE: {RESET: "READY", LOGOUT: "UNAUTHENTICATED"},
  FAIL_CLOSED: {RESET: "READY", LOGOUT: "UNAUTHENTICATED"},
});

export function transition(state, event) {
  const next = TRANSITIONS[state]?.[event];
  if (!next) throw new Error(`invalid chat transition: ${state} --${event}--> ?`);
  return next;
}

export function createChatMachine(initial = CHAT_STATE.UNAUTHENTICATED) {
  if (!Object.hasOwn(TRANSITIONS, initial)) throw new Error(`unknown chat state: ${initial}`);
  let state = initial;
  const history = [state];
  return Object.freeze({
    get state() { return state; },
    get history() { return Object.freeze([...history]); },
    send(event) {
      state = transition(state, event);
      history.push(state);
      return state;
    },
  });
}

export function serverOutcome(answer) {
  if (!answer || typeof answer !== "object") return "FAIL";
  if (answer.status === "requires_human_review" || answer.decision_reason === "contradictory_authoritative_evidence") {
    return "SERVER_CONFLICT";
  }
  if (answer.status !== "answered") return "SERVER_NO_EVIDENCE";
  if (!Array.isArray(answer.citations) || answer.citations.length === 0) return "FAIL";
  return "SERVER_EVIDENCE";
}

export function replayServerOutcome(machine, answer) {
  // The client records, rather than predicts, the server path. POLICY_CHECK remains
  // visible until the server has returned an authoritative outcome.
  const outcome = serverOutcome(answer);
  if (outcome === "FAIL") {
    machine.send("FAIL");
    return machine.state;
  }
  machine.send("SERVER_SEARCHED");
  machine.send(outcome);
  if (outcome === "SERVER_EVIDENCE") machine.send("ANSWER_ACCEPTED");
  machine.send("AUDIT_BEGIN");
  // A successful answer response exists only after server-side audit append returned.
  machine.send("AUDIT_OK");
  return machine.state;
}
