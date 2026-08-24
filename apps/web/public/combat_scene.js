const TAU = Math.PI * 2;

export function mountCombatScene() {
  const host = document.querySelector(".chat-stage") ?? document.querySelector(".welcome");
  if (!host || host.querySelector("#combat-signal-field")) return () => {};

  const canvas = document.createElement("canvas");
  canvas.id = "combat-signal-field";
  canvas.setAttribute("aria-hidden", "true");
  host.prepend(canvas);
  const context = canvas.getContext("2d", {alpha: true});
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const pointer = {x: .57, y: .38, targetX: .57, targetY: .38};
  let width = 0, height = 0, frame = 0, raf = 0, active = true;

  const embers = Array.from({length: 38}, (_, index) => ({
    x: ((index * 47) % 101) / 101,
    y: ((index * 71) % 103) / 103,
    speed: .00009 + (index % 7) * .000018,
    drift: ((index % 5) - 2) * .000016,
    size: .5 + (index % 4) * .42,
    phase: index * .73,
  }));

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
    draw(performance.now());
  }

  function contours(time) {
    context.save();
    context.lineWidth = .7;
    for (let band = -3; band < 17; band += 1) {
      context.beginPath();
      for (let x = -20; x <= width + 20; x += 12) {
        const nx = x / Math.max(width, 1);
        const ridge = Math.sin(nx * 8.4 + band * .71 + time * .00005) * 16;
        const detail = Math.sin(nx * 21 - band * .37) * 5;
        const focus = Math.exp(-Math.pow(nx - pointer.x, 2) * 5) * Math.sin(nx * 13 + band) * 18;
        const y = band * 54 - 80 + ridge + detail + focus + pointer.y * 38;
        if (x < 0) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.strokeStyle = band % 4 === 0 ? "rgba(255,104,43,.18)" : "rgba(154,143,82,.095)";
      context.stroke();
    }
    context.restore();
  }

  function radar(time) {
    const x = width * pointer.x;
    const y = height * pointer.y;
    const radius = Math.min(width, height) * .43;
    const angle = time * .00034;
    const gradient = context.createConicGradient(angle, x, y);
    gradient.addColorStop(0, "rgba(255,86,26,.20)");
    gradient.addColorStop(.035, "rgba(255,112,48,.02)");
    gradient.addColorStop(.28, "transparent");
    gradient.addColorStop(1, "transparent");
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(x, y, radius, 0, TAU);
    context.fill();
    context.strokeStyle = "rgba(255,105,43,.065)";
    context.setLineDash([2, 11]);
    for (const scale of [.34, .67, 1]) {
      context.beginPath();
      context.arc(x, y, radius * scale, 0, TAU);
      context.stroke();
    }
    context.setLineDash([]);
  }

  function particles(time) {
    context.save();
    context.globalCompositeOperation = "lighter";
    for (const ember of embers) {
      const life = (ember.y - time * ember.speed) % 1;
      const y = (life < 0 ? life + 1 : life) * height;
      const x = (ember.x + Math.sin(time * .00035 + ember.phase) * .018 + time * ember.drift) % 1 * width;
      const alpha = .12 + .36 * Math.pow(Math.sin((life + ember.phase) * Math.PI), 2);
      const glow = context.createRadialGradient(x, y, 0, x, y, ember.size * 5);
      glow.addColorStop(0, `rgba(255,142,67,${alpha})`);
      glow.addColorStop(1, "transparent");
      context.fillStyle = glow;
      context.fillRect(x - ember.size * 5, y - ember.size * 5, ember.size * 10, ember.size * 10);
    }
    context.restore();
  }

  function draw(time) {
    if (!active || !context) return;
    pointer.x += (pointer.targetX - pointer.x) * .035;
    pointer.y += (pointer.targetY - pointer.y) * .035;
    context.clearRect(0, 0, width, height);
    contours(time);
    radar(time);
    particles(time);
    frame += 1;
    if (!reduced.matches && !document.hidden) raf = requestAnimationFrame(draw);
  }

  function move(event) {
    const rect = host.getBoundingClientRect();
    pointer.targetX = Math.max(.12, Math.min(.88, (event.clientX - rect.left) / rect.width));
    pointer.targetY = Math.max(.16, Math.min(.72, (event.clientY - rect.top) / rect.height));
  }
  function visibility() {
    cancelAnimationFrame(raf);
    if (!document.hidden && active) raf = requestAnimationFrame(draw);
  }

  addEventListener("resize", resize, {passive: true});
  host.addEventListener("pointermove", move, {passive: true});
  document.addEventListener("visibilitychange", visibility);
  resize();
  if (!reduced.matches) raf = requestAnimationFrame(draw);

  return () => {
    active = false;
    cancelAnimationFrame(raf);
    removeEventListener("resize", resize);
    host.removeEventListener("pointermove", move);
    document.removeEventListener("visibilitychange", visibility);
    canvas.remove();
  };
}
