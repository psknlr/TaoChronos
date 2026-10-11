// Collisions in a drawn figure, as a reader sees them (tests/test_figure_layout.py runs this in Chromium on both
// renderers' figures):
// * a label over a label — each label's ink: its advance width × [baseline − 0.84 em, baseline + 0.16 em] (the glyphs,
//   not the font's taller line box), through its transform (a turned label is a turned rectangle), tested by the
//   separating-axis theorem;
// * a label off the figure (outside the root's viewBox);
// * a label over a mark: a dot or a bubble (circle), a series line (polyline), a timeline's stem (a line with a
//   stroke-opacity), a filled bar (path, rect) unless the label lies wholly inside it (a heatmap cell's own number).
function ink(t) {
  const b = t.getBBox();
  const fs = parseFloat(t.getAttribute("font-size")) || 11;
  const y = parseFloat(t.getAttribute("y") || "0");
  const m = t.getCTM();
  const pt = (x, yy) => ({ x: m.a * x + m.c * yy + m.e, y: m.b * x + m.d * yy + m.f });
  const s = 0.6, top = y - 0.84 * fs + s, bottom = y + 0.16 * fs - s;
  return [pt(b.x + s, top), pt(b.x + b.width - s, top), pt(b.x + b.width - s, bottom), pt(b.x + s, bottom)];
}
function project(poly, ax) {
  let lo = Infinity, hi = -Infinity;
  for (const p of poly) { const v = p.x * ax.x + p.y * ax.y; lo = Math.min(lo, v); hi = Math.max(hi, v); }
  return [lo, hi];
}
function intersect(a, b) {
  for (const poly of [a, b]) for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length], ax = { x: -(q.y - p.y), y: q.x - p.x };
    const [a0, a1] = project(a, ax), [b0, b1] = project(b, ax);
    if (a1 <= b0 || b1 <= a0) return false;
  }
  return true;
}
function inside(p, poly) {
  let sign = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length], c = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
    if (Math.abs(c) > 1e-9) { if (!sign) sign = Math.sign(c); else if (Math.sign(c) !== sign) return false; }
  }
  return true;
}
function distSeg(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0;
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}
const at = (el, x, y) => { const m = el.getCTM(); return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f }; };
function segHits(a, b, poly) {
  const n = Math.max(2, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y)));
  for (let i = 0; i <= n; i++) if (inside({ x: a.x + ((b.x - a.x) * i) / n, y: a.y + ((b.y - a.y) * i) / n }, poly)) return true;
  return false;
}
function boxPoly(el) {
  const b = el.getBBox();
  return [at(el, b.x, b.y), at(el, b.x + b.width, b.y), at(el, b.x + b.width, b.y + b.height), at(el, b.x, b.y + b.height)];
}
const name = (t) => `「${t.textContent.trim().slice(0, 24)}」`;

export function collisions(svg) {
  const texts = [...svg.querySelectorAll("text")].filter((t) => t.textContent.trim() && !t.closest("title"));
  const polys = texts.map(ink);
  const out = new Set();
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) if (intersect(polys[i], polys[j])) out.add(`${name(texts[i])} × ${name(texts[j])}`);
  const vb = svg.viewBox.baseVal, inv = svg.getCTM().inverse();
  texts.forEach((t, i) => {
    const pts = polys[i].map((p) => ({ x: inv.a * p.x + inv.c * p.y + inv.e, y: inv.b * p.x + inv.d * p.y + inv.f }));
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    if (Math.min(...xs) < vb.x - 0.5 || Math.max(...xs) > vb.x + vb.width + 0.5 || Math.min(...ys) < vb.y - 0.5 || Math.max(...ys) > vb.y + vb.height + 0.5) out.add(`${name(t)} off the figure`);
  });
  for (const c of svg.querySelectorAll("circle")) {
    const m = c.getCTM(), r = parseFloat(c.getAttribute("r")) * Math.sqrt(Math.abs(m.a * m.d - m.b * m.c));
    if (!(r >= 1.5)) continue;
    const p = at(c, parseFloat(c.getAttribute("cx")), parseFloat(c.getAttribute("cy")));
    polys.forEach((poly, i) => { if (inside(p, poly) || poly.some((a, k) => distSeg(p, a, poly[(k + 1) % 4]) < r - 0.5)) out.add(`${name(texts[i])} × a dot`); });
  }
  for (const l of svg.querySelectorAll("line[stroke-opacity]")) {
    const a = at(l, +l.getAttribute("x1"), +l.getAttribute("y1")), b = at(l, +l.getAttribute("x2"), +l.getAttribute("y2"));
    polys.forEach((poly, i) => { if (segHits(a, b, poly)) out.add(`${name(texts[i])} × a stem`); });
  }
  for (const pl of svg.querySelectorAll("polyline")) {
    const pts = pl.getAttribute("points").trim().split(/\s+/).map((s) => s.split(",").map(Number)).map(([x, y]) => at(pl, x, y));
    polys.forEach((poly, i) => { if (pts.slice(1).some((p, k) => segHits(pts[k], p, poly))) out.add(`${name(texts[i])} × a line`); });
  }
  for (const el of svg.querySelectorAll("path, rect")) {
    if (el.getAttribute("width") === "100%" || el.getAttribute("fill") === "none" || !el.getAttribute("fill")) continue;
    const bp = boxPoly(el);
    polys.forEach((poly, i) => { if (intersect(poly, bp) && !poly.every((q) => inside(q, bp))) out.add(`${name(texts[i])} × a bar`); });
  }
  return [...out];
}
