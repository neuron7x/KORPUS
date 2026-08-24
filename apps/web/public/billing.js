// Consumer billing surface. KORPUS decides what is for sale; the browser only renders it.
// A checkout descriptor is accepted only for the one provider endpoint this build knows.
// No amount, currency, account or subscription state is authored here.

import {ApiRefusal, call, escapeHtml} from "./api.js";

const LIQPAY_CHECKOUT = "https://www.liqpay.ua/api/3/checkout";

export function formatMoney(priceMinor, currency) {
  if (!Number.isInteger(priceMinor) || priceMinor <= 0 || !/^[A-Z]{3}$/.test(currency ?? "")) {
    return "—";
  }
  try {
    return new Intl.NumberFormat("uk-UA", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(priceMinor / 100);
  } catch {
    return `${(priceMinor / 100).toFixed(2)} ${currency}`;
  }
}

export function subscriptionLabel(state) {
  const status = state?.subscription_status;
  if (status === "active") return "Підписка активна";
  if (status === "past_due") return "Платіж прострочено";
  if (status === "canceled") return "Підписку скасовано";
  if (status === "expired") return "Підписка завершена";
  if (status === "incomplete") return "Очікується оплата";
  return state?.enforced ? "Підписка потрібна" : "Підписка не обов’язкова";
}

export function planCards(plans, {activePlan = null} = {}) {
  if (!Array.isArray(plans) || plans.length === 0) {
    return `<article class="empty-state"><strong>Тарифи ще не опубліковані.</strong>` +
      `<p>Оператор не налаштував жодного доступного для оплати плану.</p></article>`;
  }
  return plans.map(plan => {
    const sellable = Boolean(plan.sellable);
    const current = activePlan === plan.code;
    const corpora = Array.isArray(plan.entitled_corpora) ? plan.entitled_corpora : [];
    const cadence = plan.billing_interval === "yearly" ? "рік" : "місяць";
    return `<article class="plan-card${current ? " current-plan" : ""}">` +
      `<div class="plan-kicker">${current ? "ПОТОЧНИЙ ПЛАН" : "ДОСТУП"}</div>` +
      `<h3>${escapeHtml(plan.name)}</h3>` +
      `<div class="plan-price"><strong>${escapeHtml(formatMoney(plan.price_minor, plan.currency))}</strong>` +
      `<span>/ ${cadence}</span></div>` +
      `<p class="plan-copy">${corpora.length ? `Корпуси: ${escapeHtml(corpora.join(", "))}` : "Доступ визначається політикою сервера."}</p>` +
      `<button type="button" data-checkout-plan="${escapeHtml(plan.code)}"` +
      `${!sellable || current ? " disabled" : ""}>${current ? "Активний" : sellable ? "Оформити підписку" : "Недоступно"}</button>` +
      `</article>`;
  }).join("");
}

export function validateCheckoutDescriptor(descriptor) {
  if (!descriptor || descriptor.provider !== "liqpay" || descriptor.method !== "POST") {
    throw new Error("unsupported checkout descriptor");
  }
  if (descriptor.action_url !== LIQPAY_CHECKOUT) {
    throw new Error("checkout destination is not allow-listed");
  }
  const keys = Object.keys(descriptor.fields ?? {}).sort();
  if (keys.join(",") !== "data,signature") throw new Error("unexpected checkout fields");
  if (!descriptor.fields.data || !descriptor.fields.signature) {
    throw new Error("checkout descriptor is incomplete");
  }
  return descriptor;
}

export function submitCheckout(descriptor) {
  const safe = validateCheckoutDescriptor(descriptor);
  const form = document.createElement("form");
  form.method = "POST";
  form.action = safe.action_url;
  form.hidden = true;
  for (const [name, value] of Object.entries(safe.fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.append(input);
  }
  document.body.append(form);
  form.submit();
}

export async function loadCommerce() {
  const [account, subscription, plans] = await Promise.all([
    call("/v1/account"),
    call("/v1/subscription"),
    call("/v1/plans"),
  ]);
  return {account, subscription, plans};
}

export function createBillingController({pricing, plansNode, statusNode, accountNode, onState}) {
  let state = null;

  function render(loaded) {
    state = loaded;
    const subscription = loaded.subscription;
    const active = subscription?.subscription_status === "active";
    statusNode.textContent = subscriptionLabel(subscription);
    statusNode.dataset.tone = active ? "ok" : subscription?.enforced ? "warn" : "neutral";
    if (accountNode) {
      const account = loaded.account;
      accountNode.textContent = account?.display_name || account?.email || "Обліковий запис KORPUS";
    }
    plansNode.innerHTML = planCards(loaded.plans, {activePlan: subscription?.plan_code ?? null});
    pricing.hidden = active || !subscription?.enforced;
    onState?.({active, enforced: Boolean(subscription?.enforced), ...loaded});
  }

  async function refresh() {
    try {
      render(await loadCommerce());
      return state;
    } catch (error) {
      // A deployment can deliberately have the commercial services absent. That is not
      // permission for the browser to assume access or synthesize a free plan.
      statusNode.textContent = error instanceof ApiRefusal
        ? `Комерційний контур недоступний · ${error.reason}`
        : "Комерційний контур недоступний";
      statusNode.dataset.tone = "warn";
      onState?.({active: false, enforced: true, unavailable: true});
      return null;
    }
  }

  plansNode.addEventListener("click", async event => {
    const button = event.target.closest("[data-checkout-plan]");
    if (!button || button.disabled) return;
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Готую оплату…";
    try {
      const descriptor = await call("/v1/billing/checkout", {
        method: "POST",
        body: {plan_code: button.dataset.checkoutPlan},
      });
      submitCheckout(descriptor);
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      statusNode.textContent = error instanceof ApiRefusal
        ? `Checkout відхилено · ${error.reason}`
        : "Checkout недоступний";
      statusNode.dataset.tone = "warn";
    }
  });

  return {refresh, render};
}
