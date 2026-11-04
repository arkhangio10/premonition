"use strict";

// Original abstract visualization: these positions do not represent the physical arm.
(() => {
  const panel = document.getElementById("state-map");
  const canvas = document.getElementById("orbit-canvas");
  const ctx = canvas.getContext("2d");
  const buttons = [...panel.querySelectorAll(".part-node")];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const narrow = matchMedia("(max-width: 760px)");
  let width = 0, height = 0, yaw = -.3, pitch = .12, zoom = 1;
  let drag = null, pointer = null, frame = null, previous = 0, dirty = true;
  let seed = 427;
  const random = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const points = Array.from({length:2000}, (_, i) => {
    const y = 1 - 2 * (i + .5) / 2000, angle = i * Math.PI * (3 - Math.sqrt(5));
    const radial = Math.sqrt(1 - y * y), r = .78 + random() * .22;
    return {x:Math.cos(angle) * radial * r,y:y * r,z:Math.sin(angle) * radial * r,size:.45 + random() * .9};
  });
  function project(point, cx, cy, radius) {
    const x = point.x * Math.cos(yaw) - point.z * Math.sin(yaw);
    const z = point.x * Math.sin(yaw) + point.z * Math.cos(yaw);
    const y = point.y * Math.cos(pitch) - z * Math.sin(pitch);
    const depth = point.y * Math.sin(pitch) + z * Math.cos(pitch);
    const scale = 3.8 / (3.8 - depth);
    return {x:cx + x * radius * scale,y:cy + y * radius * scale,z:depth,scale};
  }
  function draw(time) {
    frame = null;
    if (document.hidden || panel.hidden || !ctx) return;
    if (time - previous < 32 && !dirty) { schedule(); return; }
    const elapsed = Math.min(time - previous || 32, 64); previous = time;
    if (!reduced.matches && !drag) yaw += elapsed * .000035;
    dirty = false;
    ctx.clearRect(0, 0, width, height);
    const mobile = narrow.matches;
    const cx = width * (mobile ? .49 : .665), cy = height * (mobile ? .655 : .49);
    const radius = Math.min(width * (mobile ? .34 : .235), height * (mobile ? .215 : .42)) * zoom;
    for (let ring = 0; ring < 3; ring++) {
      for (let i = 0; i < 180; i++) {
        const angle = i / 180 * Math.PI * 2;
        const p = project({x:Math.cos(angle) * 1.29,y:Math.sin(angle) * .42,z:Math.sin(angle) * 1.15}, cx, cy, radius);
        ctx.fillStyle = `rgba(28,29,28,${.11 + (p.z + 1.2) * .04})`;
        ctx.fillRect(p.x + ring * .018 * radius, p.y + ring * .018 * radius, .7, .7);
      }
    }
    const projected = [];
    for (let i = 0; i < points.length; i += mobile ? 2 : 1) projected.push({...project(points[i], cx, cy, radius),size:points[i].size});
    projected.sort((a,b) => a.z - b.z);
    for (const p of projected) {
      let x = p.x, y = p.y;
      if (pointer && !reduced.matches) {
        const dx = x - pointer.x, dy = y - pointer.y, distance = Math.hypot(dx, dy);
        if (distance > 0 && distance < 65) { const push = (1 - distance / 65) * 4; x += dx / distance * push; y += dy / distance * push; }
      }
      ctx.fillStyle = `rgba(28,29,28,${.16 + (p.z + 1) * .35})`;
      ctx.beginPath(); ctx.arc(x, y, p.size * p.scale, 0, Math.PI * 2); ctx.fill();
    }
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * .28);
    glow.addColorStop(0, "rgba(229,91,43,.15)"); glow.addColorStop(1, "rgba(229,91,43,0)");
    ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, radius * .28, 0, Math.PI * 2); ctx.fill();
    for (let i = 0; i < 65; i++) {
      const angle = i * 2.39996, r = Math.sqrt(i / 65) * radius * .16;
      ctx.fillStyle = i % 4 ? "#e55b2b" : "#99381c";
      ctx.fillRect(cx + Math.cos(angle) * r, cy + Math.sin(angle) * r * .7, 1.1, 1.1);
    }
    // Stable labels preserve legibility and keyboard targets while the cloud rotates.
    const anchors = mobile ? [[.18,.50],[.66,.67],[.28,.83]] : [[.52,.23],[.84,.47],[.59,.79]];
    anchors.forEach(([ax,ay], i) => {
      const x = Math.max(36, Math.min(width - buttons[i].offsetWidth + 12, width * ax)), y = height * ay;
      ctx.strokeStyle = "rgba(28,29,28,.17)"; ctx.lineWidth = .6;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
      buttons[i].style.left = `${x}px`; buttons[i].style.top = `${y}px`;
    });
    if (!reduced.matches || drag) schedule();
  }
  function schedule() { if (!frame && ctx && !document.hidden && !panel.hidden) frame = requestAnimationFrame(draw); }
  function invalidate() { dirty = true; schedule(); }
  function resize() {
    if (!ctx) return;
    const bounds = panel.getBoundingClientRect(); if (!bounds.width || !bounds.height) return;
    width = bounds.width; height = bounds.height;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0); invalidate();
  }
  function update(view) {
    const active = view.steps.find((step) => step.step_id === view.current_step);
    const relevant = active?.target_step_id ? view.steps.find((step) => step.step_id === active.target_step_id) : active;
    buttons.forEach((button) => {
      const actions = view.steps.filter((step) => step.piece_id === button.dataset.part && ["pick","place"].includes(step.action));
      const complete = actions.length >= 2 && actions.every((step) => step.outcome === "pass");
      const review = !complete && actions.some((step) => ["fail","unknown"].includes(step.outcome)) && view.status !== "running";
      const inProgress = !complete && ((view.status === "running" && relevant?.piece_id === button.dataset.part) || actions.some((step) => step.outcome === "pass"));
      const state = complete ? "verified" : review ? "review" : inProgress ? "active" : "pending";
      button.dataset.state = state;
      const label = {verified:"Verified",review:"Review",active:view.status === "running" ? "In progress" : "Incomplete",pending:"Not started"}[state];
      button.querySelector("small").textContent = label;
      button.querySelector(".node-target").textContent = {verified:"✓",review:"!",active:"·",pending:"+"}[state];
      button.setAttribute("aria-label", `Part ${button.dataset.part}: ${label}. View step results`);
    });
    document.getElementById("map-status").textContent = `${{running:"Checking",completed:"Kit verified",stopped:"Stopped"}[view.status] || "Ready"} / 3 parts`;
    invalidate();
  }
  buttons.forEach((button) => button.addEventListener("click", () => document.dispatchEvent(new CustomEvent("premonition:inspect", {detail:button.dataset.part}))));
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    drag = {x:event.clientX,y:event.clientY}; canvas.setPointerCapture(event.pointerId); canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointermove", (event) => {
    const bounds = canvas.getBoundingClientRect(); pointer = {x:event.clientX - bounds.left,y:event.clientY - bounds.top};
    if (drag) { yaw += (event.clientX - drag.x) * .005; pitch = Math.max(-.7, Math.min(.7, pitch + (event.clientY - drag.y) * .004)); drag = {x:event.clientX,y:event.clientY}; }
    invalidate();
  });
  const release = () => { drag = null; canvas.classList.remove("dragging"); invalidate(); };
  canvas.addEventListener("pointerup", release); canvas.addEventListener("pointercancel", release); canvas.addEventListener("lostpointercapture", release);
  canvas.addEventListener("pointerleave", () => { pointer = null; invalidate(); });
  canvas.addEventListener("wheel", (event) => { if (!event.ctrlKey) return; event.preventDefault(); zoom = Math.max(.7, Math.min(1.3, zoom - event.deltaY * .002)); invalidate(); }, {passive:false});
  panel.querySelector(".orbit-hint").textContent = "Drag to rotate · Ctrl + scroll to zoom";
  document.getElementById("reset-orbit").addEventListener("click", () => { yaw = -.3; pitch = .12; zoom = 1; invalidate(); });
  document.addEventListener("premonition:state", (event) => update(event.detail));
  document.addEventListener("premonition:view", () => { if (panel.hidden) { cancelAnimationFrame(frame); frame = null; } else resize(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(frame); frame = null; } else invalidate(); });
  reduced.addEventListener("change", invalidate);
  if (!ctx) { canvas.hidden = true; buttons.forEach((button,i) => { button.style.left = `${30 + i * 20}%`; button.style.top = "65%"; }); return; }
  new ResizeObserver(resize).observe(panel); resize();
})();
