import test from "node:test";
import assert from "node:assert/strict";
import {ApiRefusal, NetworkError, describeError} from "../public/api.js";

test("typed throttling remains actionable without exposing a generic status code", () => {
  const error = new ApiRefusal(429, "API 429", {
    detail: {reason: "subject_share_exhausted", detail: "Ліміт одночасних запитів вичерпано"},
  });
  assert.deepEqual(describeError(error), {
    title: "ЛІМІТ ЗАПИТІВ",
    message: "Ліміт одночасних запитів вичерпано",
  });
});

test("a lost link is distinguished from a server refusal", () => {
  assert.deepEqual(describeError(new NetworkError(true)), {
    title: "НЕМАЄ ЗВ’ЯЗКУ",
    message: "Запит не втрачено. Перевірте з’єднання та повторіть спробу.",
  });
});
