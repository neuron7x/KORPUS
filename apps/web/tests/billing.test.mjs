import test from "node:test";
import assert from "node:assert/strict";

import {
  formatMoney, planCards, subscriptionLabel, validateCheckoutDescriptor,
} from "../public/billing.js";

test("money is formatted from integer minor units", () => {
  const rendered = formatMoney(19900, "UAH");
  assert.match(rendered, /199/);
  assert.notEqual(rendered, "—");
  assert.equal(formatMoney(0, "UAH"), "—");
  assert.equal(formatMoney(19900, "uah"), "—");
});

test("commercial status does not call incomplete active", () => {
  assert.equal(subscriptionLabel({subscription_status: "active"}), "Підписка активна");
  assert.equal(subscriptionLabel({subscription_status: "incomplete"}), "Очікується оплата");
  assert.equal(subscriptionLabel({enforced: true}), "Підписка потрібна");
});

test("a plan price and corpus label are escaped", () => {
  const html = planCards([{
    code: "standard",
    name: '<img src=x onerror="x">',
    billing_interval: "monthly",
    price_minor: 19900,
    currency: "UAH",
    sellable: true,
    entitled_corpora: ["training<script>"],
  }]);
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /data-checkout-plan="standard"/);
});

test("checkout is allow-listed to the exact LiqPay endpoint", () => {
  const descriptor = {
    provider: "liqpay",
    method: "POST",
    action_url: "https://www.liqpay.ua/api/3/checkout",
    fields: {data: "abc", signature: "sig"},
  };
  assert.equal(validateCheckoutDescriptor(descriptor), descriptor);
  assert.throws(
    () => validateCheckoutDescriptor({...descriptor, action_url: "https://evil.example/pay"}),
    /allow-listed/,
  );
  assert.throws(
    () => validateCheckoutDescriptor({...descriptor, fields: {...descriptor.fields, amount: "1"}}),
    /unexpected checkout fields/,
  );
});
