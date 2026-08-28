const TAU = Math.PI * 2;
const HOSTILE_BLIPS = [
  [.18, .42, .1], [.63, .58, .34], [1.17, .76, .61], [1.72, .49, .83], [2.41, .68, .22],
];
function sourceContact(source, index) {
  const identity = String(source.source_hash ?? source.span_id ?? index);
  let hash = 2166136261;
  for (const code of identity) hash = Math.imul(hash ^ code.charCodeAt(0), 16777619) >>> 0;
  return {
    angle: ((hash % 3600) / 3600) * TAU,
    radius: .24 + (((hash >>> 12) % 650) / 1000),
    phase: ((hash >>> 22) % 100) / 100,
  };
}

export function mountCombatScene() {
  const host = document.querySelector(".chat-stage") ?? document.querySelector(".welcome");
  if (!host || host.querySelector("#combat-signal-field")) return () => {};

  const canvas = document.createElement("canvas");
  canvas.id = "combat-signal-field";
  canvas.setAttribute("aria-hidden", "true");
  host.prepend(canvas);
  const context = canvas.getContext("2d", {alpha: true});
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const viewport = globalThis.visualViewport;
  const signal = {stage: -1, state: "READY", coverage: 0, contacts: []};
  const hostile = {visible: true, count: 3, changedAt: performance.now()};
  let width = 0, height = 0, centerX = 0, centerY = 0, raf = 0, active = true;
  const heartbeat = setInterval(() => {
    hostile.visible = !hostile.visible;
    if (hostile.visible) hostile.count = hostile.count === 5 ? 3 : hostile.count + 1;
    hostile.changedAt = performance.now();
    draw(hostile.changedAt);
  }, 1400);

  function updateState() {
    canvas.dataset.contacts = String(signal.contacts.length);
    canvas.dataset.stage = String(signal.stage);
    canvas.dataset.coverage = String(Math.round(signal.coverage * 100));
  }

  function onSignal(event) {
    const detail = event.detail ?? {};
    if (Number.isInteger(detail.stage)) signal.stage = Math.max(-1, Math.min(3, detail.stage));
    if (typeof detail.state === "string") signal.state = detail.state.slice(0, 32).toUpperCase();
    if (Number.isFinite(detail.coverage)) signal.coverage = Math.max(0, Math.min(1, detail.coverage));
    if (Array.isArray(detail.sources)) signal.contacts = detail.sources.slice(0, 12).map(sourceContact);
    updateState();
    draw(performance.now());
  }

  function resize() {
    const rect = host.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio || 1, 1.6);
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const canvasRect = canvas.getBoundingClientRect();
    const promptRect = host.querySelector(".empty-chat h2")?.getBoundingClientRect();
    centerX = promptRect ? promptRect.left + promptRect.width / 2 - canvasRect.left : width / 2;
    const radius = Math.max(72, Math.min(width * .32, height * .25, (viewport?.height ?? innerHeight) * .28, 250));
    const promptTop = promptRect ? promptRect.top - canvasRect.top : height * .54;
    centerY = Math.max(radius + 18, Math.min(promptTop - radius - 24, 270));
    canvas.dataset.centerX = String(centerX);
    canvas.dataset.centerY = String(centerY);
    canvas.dataset.radius = String(radius);
    draw(performance.now());
  }

  function grid(x, y, radius, angle) {
    context.save();
    context.strokeStyle = "rgba(67,240,139,.12)";
    context.lineWidth = .7;
    for (const scale of [.25, .5, .75, 1]) {
      context.beginPath();
      context.arc(x, y, radius * scale, 0, TAU);
      context.stroke();
    }
    for (let axis = 0; axis < 4; axis += 1) {
      const theta = axis * Math.PI / 2;
      context.beginPath();
      context.moveTo(x, y);
      context.lineTo(x + Math.cos(theta) * radius, y + Math.sin(theta) * radius);
      context.stroke();
    }
    const sweep = context.createConicGradient(angle, x, y);
    sweep.addColorStop(0, "rgba(67,240,139,.28)");
    sweep.addColorStop(.045, "rgba(67,240,139,.025)");
    sweep.addColorStop(.24, "transparent");
    sweep.addColorStop(1, "transparent");
    context.fillStyle = sweep;
    context.beginPath();
    context.arc(x, y, radius, 0, TAU);
    context.fill();
    context.restore();
  }

  function stages(x, y, radius) {
    for (let index = 0; index < 4; index += 1) {
      const theta = -Math.PI / 2 + index * Math.PI / 2;
      const sx = x + Math.cos(theta) * radius * .72;
      const sy = y + Math.sin(theta) * radius * .72;
      context.fillStyle = index <= signal.stage ? "#62f49b" : "rgba(120,170,139,.38)";
      context.fillRect(sx - 2, sy - 2, 4, 4);
    }
  }

  function contacts(x, y, radius, time) {
    context.save();
    context.globalCompositeOperation = "lighter";
    signal.contacts.forEach(contact => {
      const cx = x + Math.cos(contact.angle) * radius * contact.radius;
      const cy = y + Math.sin(contact.angle) * radius * contact.radius;
      const pulse = reduced.matches ? 5 : 5 + Math.sin(time * .004 + contact.phase * TAU) * 2;
      context.strokeStyle = "rgba(98,244,155,.72)";
      context.beginPath();
      context.arc(cx, cy, pulse, 0, TAU);
      context.stroke();
      context.fillStyle = "#9df7bd";
      context.fillRect(cx - 1.5, cy - 1.5, 3, 3);
    });
    context.restore();
  }

  function hostileBlips(x, y, radius, time) {
    if (!hostile.visible) {
      canvas.dataset.hostiles = "0";
      return;
    }
    const edgeFade = reduced.matches ? .82 : Math.min(1, (time - hostile.changedAt) / 180);
    const count = hostile.count;
    canvas.dataset.hostiles = String(count);
    context.save();
    context.globalCompositeOperation = "lighter";
    HOSTILE_BLIPS.slice(0, count).forEach(([turn, distance, phase]) => {
      const angle = turn * Math.PI + phase * .08;
      const bx = x + Math.cos(angle) * radius * distance;
      const by = y + Math.sin(angle) * radius * distance;
      const pulse = reduced.matches ? 5 : 5 + Math.sin(time * .008 + phase * TAU) * 1.8;
      context.globalAlpha = edgeFade * (reduced.matches ? 1 : .82 + Math.sin(time * .005 + phase * 9) * .16);
      context.shadowColor = "rgba(255,45,32,.92)";
      context.shadowBlur = 9;
      context.fillStyle = "#ff2d20";
      context.fillRect(Math.round(bx) - 2.5, Math.round(by) - 2.5, 5, 5);
      context.shadowBlur = 3;
      context.strokeStyle = "rgba(255,88,72,.88)";
      context.lineWidth = 1;
      context.beginPath();
      context.arc(bx, by, pulse, 0, TAU);
      context.stroke();
    });
    context.restore();
  }

  function draw(time) {
    if (!active || !context) return;
    context.clearRect(0, 0, width, height);
    const x = centerX;
    const radius = Number(canvas.dataset.radius);
    const y = centerY;
    grid(x, y, radius, reduced.matches ? 0 : time * .00042);
    stages(x, y, radius);
    contacts(x, y, radius, time);
    hostileBlips(x, y, radius, time);
    if (!reduced.matches && !document.hidden && !raf) raf = requestAnimationFrame(frame);
  }

  function frame(time) {
    raf = 0;
    draw(time);
  }

  function visibility() {
    cancelAnimationFrame(raf);
    raf = 0;
    if (!document.hidden && active) raf = requestAnimationFrame(frame);
  }

  const observer = new ResizeObserver(resize);
  observer.observe(host);
  addEventListener("resize", resize, {passive: true});
  viewport?.addEventListener("resize", resize, {passive: true});
  addEventListener("korpus:radar", onSignal);
  document.addEventListener("visibilitychange", visibility);
  updateState();
  resize();
  if (!reduced.matches) raf = requestAnimationFrame(frame);

  return () => {
    active = false;
    clearInterval(heartbeat);
    cancelAnimationFrame(raf);
    observer.disconnect();
    removeEventListener("resize", resize);
    viewport?.removeEventListener("resize", resize);
    removeEventListener("korpus:radar", onSignal);
    document.removeEventListener("visibilitychange", visibility);
    canvas.remove();
  };
}
