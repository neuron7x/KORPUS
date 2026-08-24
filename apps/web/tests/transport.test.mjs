import test from "node:test";
import assert from "node:assert/strict";

import {assertTransportRoute, authHeaders} from "../public/api.js";

test("generated transport contract admits the server bootstrap and dynamic API routes", () => {
  assert.equal(assertTransportRoute("/v1/client/bootstrap", "GET"), true);
  assert.equal(assertTransportRoute("/v1/conversations/abc-123", "GET"), true);
  assert.equal(assertTransportRoute("/v1/auth/logout", "POST"), true);
});

test("stale endpoints and wrong methods fail before a network request", () => {
  assert.throws(() => assertTransportRoute("/v1/client/bootstrap", "POST"), /transport contract refuses/);
  assert.throws(() => assertTransportRoute("/v1/legacy-answer", "GET"), /transport contract refuses/);
});

test("client release header comes from the generated release contract", () => {
  assert.equal(authHeaders({}, "GET")["X-KORPUS-Client-Version"], "v0.9.7");
});
