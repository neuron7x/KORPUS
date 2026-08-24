// WCAG 2.2 AA checks that only exist once the page is rendered.
//
// `validate.mjs` reads the HTML: headings, accessible names, labels bound by id. Those are
// real and they are static. WEB-002 asks for the other half — keyboard traversal, focus
// visibility, target size, contrast — and none of it can be seen in a source file, because
// all four are properties of computed style and live focus.
//
// Written to run inside the page (`page.evaluate`, or a devtools console) and to return a
// report rather than throw, so a run names every failure instead of the first one.
//
// What it cannot do, and what therefore stays external: a screen reader is a piece of
// software with its own bugs and its own users, and "NVDA announces this correctly" is a
// claim only NVDA can settle. Everything here is necessary and none of it is sufficient.

(() => {
  const failures = [];
  const fail = (rule, detail) => failures.push({ rule, detail });

  const visible = (element) => {
    const style = getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const closed = element.closest("details:not([open])");
    if (closed && element !== closed.querySelector(":scope > summary")) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };

  const interactive = [...document.querySelectorAll(
    'a[href], button, input:not([type="hidden"]), select, textarea, summary, [tabindex]:not([tabindex="-1"])',
  )].filter(visible).filter((element) => !element.disabled);

  // 2.5.8 Target Size (Minimum), AA: 24 by 24 CSS pixels, measured on the control itself.
  // Inline links in a sentence are exempt; nothing here is one.
  for (const element of interactive) {
    if (element.tagName === "A" && element.closest("p, li, blockquote")) continue;
    const box = element.getBoundingClientRect();
    if (box.width < 24 || box.height < 24) {
      fail("2.5.8 target size", `${element.tagName}#${element.id || "?"} is ${Math.round(box.width)}x${Math.round(box.height)}`);
    }
  }

  // 2.4.7 Focus Visible, AA: focusing a control must change something a sighted keyboard
  // user can see. Compared against the same element unfocused rather than against a
  // hard-coded outline, because a design may signal focus with a border or a shadow.
  const signature = (element) => {
    const style = getComputedStyle(element);
    return [style.outlineStyle, style.outlineWidth, style.outlineColor, style.boxShadow,
      style.borderColor, style.backgroundColor].join("|");
  };
  for (const element of interactive) {
    const before = signature(element);
    element.focus({ preventScroll: true });
    if (document.activeElement !== element) {
      fail("2.1.1 keyboard", `${element.tagName}#${element.id || "?"} cannot take focus`);
      continue;
    }
    if (signature(element) === before) {
      fail("2.4.7 focus visible", `${element.tagName}#${element.id || "?"} looks identical focused`);
    }
  }
  document.activeElement?.blur();

  // 1.4.3 Contrast (Minimum), AA: 4.5:1 for body text, 3:1 for large text. Backgrounds are
  // walked up the tree because a transparent element inherits what is behind it.
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const parse = (colour) => {
    const parts = colour.match(/[\d.]+/g)?.map(Number);
    if (!parts || parts.length < 3) return null;
    return {rgb: parts.slice(0, 3), alpha: parts.length >= 4 ? parts[3] : 1};
  };
  const luminance = (rgb) => 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  const blend = (front, back, alpha) => front.map((value, index) => value * alpha + back[index] * (1 - alpha));
  const backgroundOf = (element) => {
    const layers = [];
    for (let node = element; node; node = node.parentElement) {
      const parsed = parse(getComputedStyle(node).backgroundColor);
      if (parsed && parsed.alpha > 0) layers.push(parsed);
    }
    let result = [0, 0, 0];
    for (const layer of layers.reverse()) result = blend(layer.rgb, result, layer.alpha);
    return result;
  };
  const textNodes = [...document.querySelectorAll("p, li, h1, h2, h3, h4, span, a, button, dd, dt, blockquote")]
    .filter((element) => visible(element) && element.textContent.trim().length > 0)
    .filter((element) => [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim()));
  for (const element of textNodes) {
    const style = getComputedStyle(element);
    const foreground = parse(style.color);
    if (!foreground) continue;
    const background = backgroundOf(element);
    const foregroundRgb = blend(foreground.rgb, background, foreground.alpha);
    const light = Math.max(luminance(foregroundRgb), luminance(background));
    const dark = Math.min(luminance(foregroundRgb), luminance(background));
    const ratio = (light + 0.05) / (dark + 0.05);
    const size = parseFloat(style.fontSize);
    const bold = Number(style.fontWeight) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const required = large ? 3 : 4.5;
    if (ratio < required) {
      fail("1.4.3 contrast", `${element.tagName} "${element.textContent.trim().slice(0, 32)}" is ${ratio.toFixed(2)}:1, needs ${required}:1`);
    }
  }

  // 2.4.1 Bypass Blocks: the skip link must reach a real target.
  const skip = document.querySelector("a.skip-link, a[href^='#']");
  if (skip) {
    const target = document.querySelector(skip.getAttribute("href"));
    if (!target) fail("2.4.1 bypass blocks", `skip link points at ${skip.getAttribute("href")}, which does not exist`);
  }

  // 4.1.2 Name, Role, Value: a live region for content that appears without a page load.
  // The answer arrives after a request; a reader who cannot see it must be told it did.
  const live = document.querySelector("[aria-live], [role='status'], [role='alert']");
  if (!live) fail("4.1.2 status messages", "no live region: content that appears is announced to nobody");

  return {
    checked: {
      interactive_controls: interactive.length,
      text_elements: textNodes.length,
    },
    failures,
    status: failures.length === 0 ? "PASS" : "FAIL",
    external: [
      "A screen reader is software with its own users and its own bugs; " +
      "'NVDA announces this correctly' is a claim only NVDA can settle.",
    ],
  };
})();
