"use strict";

// The arm in model coordinates (z up), drawn with the yaw/pitch projection and orbit of scene.js.
(() => {
  const sub = (a, b) => a.map((v, i) => v - b[i]);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = a => a.map(v => v / Math.hypot(...a));
  const niceStep = size => { const power = 10 ** Math.floor(Math.log10(size)); return [5, 2, 1].map(m => m * power).find(s => s <= size); };

  window.ArmView = class {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      const style = getComputedStyle(canvas);
      this.colors = Object.fromEntries(["arm", "rule", "quiet", "walnut", "wall"].map(name => [name, style.getPropertyValue(`--${name}`).trim()]));
      this.yaw = -.7; this.pitch = .45; this.zoom = 1;
      this.scene = {atlas: [], workspace: {scanned: [], limits: []}, table: null};
      this.center = [0, 0, 0]; this.radius = 0;
      this.chain = null; this.tips = []; this.frame = null; this.drag = null;
      canvas.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        this.drag = {x: event.clientX, y: event.clientY}; canvas.setPointerCapture(event.pointerId); canvas.classList.add("dragging");
      });
      canvas.addEventListener("pointermove", event => {
        if (!this.drag) return;
        this.yaw += (event.clientX - this.drag.x) * .005;
        this.pitch = Math.max(-.2, Math.min(1.5, this.pitch + (event.clientY - this.drag.y) * .004));
        this.drag = {x: event.clientX, y: event.clientY}; this.invalidate();
      });
      const release = () => { this.drag = null; canvas.classList.remove("dragging"); };
      canvas.addEventListener("pointerup", release); canvas.addEventListener("pointercancel", release); canvas.addEventListener("lostpointercapture", release);
      canvas.addEventListener("wheel", event => {
        if (!event.ctrlKey) return;
        event.preventDefault(); this.zoom = Math.max(.6, Math.min(2.5, this.zoom - event.deltaY * .002)); this.invalidate();
      }, {passive: false});
      new ResizeObserver(() => this.resize()).observe(canvas);
    }

    setScene({atlas, workspace, table}) {
      this.scene = {atlas, workspace, table};
      const points = [...workspace.limits, ...workspace.scanned, ...atlas];
      const low = [0, 1, 2].map(i => Math.min(...points.map(p => p[i]))), high = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])));
      this.center = low.map((v, i) => (v + high[i]) / 2);
      this.radius = Math.max(...points.map(p => Math.hypot(...sub(p, this.center))));
      this.invalidate();
    }

    setPose(chain) { this.chain = chain; this.invalidate(); }

    setTrail(tips) { this.tips = tips.slice(-40); this.invalidate(); }

    resize() {
      const {width, height} = this.canvas.getBoundingClientRect();
      if (!width || !height) return;
      const ratio = Math.min(devicePixelRatio || 1, 2);
      this.width = width; this.height = height;
      this.canvas.width = Math.round(width * ratio); this.canvas.height = Math.round(height * ratio);
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0); this.invalidate();
    }

    invalidate() { if (!this.frame) this.frame = requestAnimationFrame(() => this.draw()); }

    project(point) {
      const [x, y, z] = sub(point, this.center);
      const across = x * Math.cos(this.yaw) - y * Math.sin(this.yaw), along = x * Math.sin(this.yaw) + y * Math.cos(this.yaw);
      const up = z * Math.cos(this.pitch) + along * Math.sin(this.pitch);
      const depth = (z * Math.sin(this.pitch) - along * Math.cos(this.pitch)) / this.radius;
      const scale = 3.8 / (3.8 - depth), k = Math.min(this.width, this.height) * .6 / this.radius * this.zoom;
      return [this.width / 2 + across * k * scale, this.height / 2 - up * k * scale, scale];
    }

    line(from, to) { this.ctx.moveTo(from[0], from[1]); this.ctx.lineTo(to[0], to[1]); }

    draw() {
      this.frame = null;
      const {ctx, colors, scene} = this;
      if (!this.width || !this.radius) return;
      ctx.clearRect(0, 0, this.width, this.height);
      const normal = unit(scene.table?.normal ?? [0, 0, 1]);
      if (this.chain) this.drawTable(this.chain[0], normal);
      for (const [points, color, alpha] of [[scene.workspace.limits, colors.rule, 1], [scene.workspace.scanned, colors.quiet, .5]]) {
        ctx.globalAlpha = alpha; ctx.fillStyle = color;
        for (const point of points) { const [x, y] = this.project(point); ctx.fillRect(x, y, 1, 1); }
      }
      ctx.globalAlpha = .4; ctx.fillStyle = colors.arm;
      for (const point of scene.atlas) { const [x, y, s] = this.project(point); ctx.beginPath(); ctx.arc(x, y, 2.5 * s, 0, 2 * Math.PI); ctx.fill(); }
      this.tips.forEach((tip, i) => {
        const [x, y] = this.project(tip);
        ctx.globalAlpha = .12 + .5 * (i + 1) / this.tips.length; ctx.beginPath(); ctx.arc(x, y, 2, 0, 2 * Math.PI); ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (this.chain) this.drawChain(normal);
    }

    drawTable(foot, normal) {
      const {ctx} = this;
      const u = unit(cross(normal, Math.abs(normal[0]) < .9 ? [1, 0, 0] : [0, 1, 0])), v = cross(normal, u);
      const step = niceStep(this.radius / 5), points = [...this.scene.workspace.limits, ...this.scene.atlas, ...this.chain];
      const span = axis => { const values = points.map(p => dot(sub(p, foot), axis) / step); return [Math.floor(Math.min(...values)), Math.ceil(Math.max(...values))]; };
      const [i0, i1] = span(u), [j0, j1] = span(v);
      const at = (i, j) => this.project(foot.map((f, c) => f + (u[c] * i + v[c] * j) * step));
      ctx.fillStyle = ctx.strokeStyle = this.colors.walnut; ctx.lineWidth = 1;
      ctx.globalAlpha = .06; ctx.beginPath();
      [at(i0, j0), at(i1, j0), at(i1, j1), at(i0, j1)].forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
      ctx.fill();
      ctx.globalAlpha = .22; ctx.beginPath();
      for (let i = i0; i <= i1; i++) this.line(at(i, j0), at(i, j1));
      for (let j = j0; j <= j1; j++) this.line(at(i0, j), at(i1, j));
      ctx.stroke(); ctx.globalAlpha = 1;
    }

    drawChain(normal) {
      const {ctx, colors, chain} = this;
      const [foot, , , tip] = chain, points = chain.map(p => this.project(p));
      const below = tip.map((t, i) => t - dot(sub(tip, foot), normal) * normal[i]);
      ctx.strokeStyle = colors.quiet; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
      ctx.beginPath(); this.line(points[3], this.project(below)); ctx.stroke(); ctx.setLineDash([]);
      ctx.strokeStyle = colors.arm; ctx.lineWidth = 4; ctx.lineCap = ctx.lineJoin = "round";
      ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke();
      ctx.fillStyle = colors.wall; ctx.lineWidth = 2;
      for (const [x, y] of points.slice(1, 3)) { ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); }
      ctx.fillStyle = colors.arm; ctx.beginPath(); ctx.arc(points[3][0], points[3][1], 6, 0, 2 * Math.PI); ctx.fill();
    }
  };
})();
