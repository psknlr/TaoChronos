"""HTML template of the Discovery Workspace (self-contained: inline CSS and JS, no network)."""

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TaoChronos Workspace</title>
<style>
:root{--bg:#f7f5f0;--panel:#fffdf8;--ink:#1f2328;--muted:#6b6f76;--line:#e3ddd0;--accent:#8a3b12;--ok:#2f7d4f;--warn:#b7791f;--bad:#b42318;--chip:#efe9dc;--hl:#ffe8a3;--contest:#f3c1b5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171a;--panel:#1d2024;--ink:#e8e6e1;--muted:#9aa0a6;--line:#30343a;--accent:#e0925c;--ok:#5fbf85;--warn:#e0b060;--bad:#f07167;--chip:#2a2e34;--hl:#5b4a12;--contest:#5c2a22}}
:root[data-theme=dark]{--bg:#15171a;--panel:#1d2024;--ink:#e8e6e1;--muted:#9aa0a6;--line:#30343a;--accent:#e0925c;--ok:#5fbf85;--warn:#e0b060;--bad:#f07167;--chip:#2a2e34;--hl:#5b4a12;--contest:#5c2a22}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{margin:0;font-size:17px;letter-spacing:.02em}header h1 span{color:var(--accent)}
.q{margin:6px 0 8px;font-size:15px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:300px minmax(0,1fr) 380px;grid-template-rows:minmax(420px,62vh) auto;gap:12px;padding:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:auto;min-width:0}
.panel h2{font-size:13px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel);z-index:1}
.left{grid-row:1/3}.bottom{grid-column:2/4}
.hyp{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer}.hyp:hover{background:var(--chip)}.hyp.sel{outline:2px solid var(--accent);outline-offset:-2px}
.hyp .t{font-size:13px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.meta{font-size:11px;color:var(--muted);display:flex;gap:6px;flex-wrap:wrap;margin-bottom:3px}
.badge{border-radius:4px;padding:0 5px;font-size:11px;background:var(--chip)}
.s-survived,.s-expert_approved{color:var(--ok)}.s-rejected,.s-expert_rejected{color:var(--bad)}.s-needs_revision,.s-proposed{color:var(--warn)}
.tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel);z-index:2}
.tabs button{border:0;background:none;color:var(--muted);padding:6px 10px;border-radius:6px;cursor:pointer;font:inherit}
.tabs button.on{background:var(--chip);color:var(--ink)}
.view{padding:10px 14px;display:none}.view.on{display:block}
svg{width:100%;display:block}
.gnode circle{stroke:var(--panel);stroke-width:1.5}.gnode text{font-size:11px;fill:var(--ink);pointer-events:none}
.glink{stroke:var(--line)}.dim{opacity:.18}
.passage{padding:12px;font-size:15px;line-height:1.9;font-family:"Songti SC","Noto Serif CJK SC",serif}
mark{background:var(--hl);color:inherit;padding:0 1px}.contest{background:var(--contest);border-bottom:2px dotted var(--bad)}
.kv{font-size:12px;color:var(--muted);padding:0 12px 10px}.kv b{color:var(--ink);font-weight:600}
.section{padding:8px 12px}.section h3{font-size:12px;margin:6px 0;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.ev{padding:5px 0;border-bottom:1px dashed var(--line);cursor:pointer;font-size:13px}.ev:hover{color:var(--accent)}
.ev.contra{color:var(--bad)}.ev.context{color:var(--muted)}
.bar{display:flex;align-items:center;gap:6px;font-size:12px}.bar i{display:inline-block;height:8px;background:var(--accent);border-radius:4px}
.gates span{display:inline-block;margin:2px;padding:1px 6px;border-radius:4px;font-size:12px;background:var(--chip)}
.g-pass{color:var(--ok)}.g-fail{color:var(--bad)}.g-warn{color:var(--warn)}
table{border-collapse:collapse;font-size:12px;margin:6px 0}td,th{border:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;font-size:12px;background:var(--chip);padding:8px;border-radius:6px}
.report h1{font-size:18px}.report h2{font-size:15px;border-bottom:1px solid var(--line);padding-bottom:3px}
blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--accent);color:var(--muted)}
.task{font-size:12px;padding:3px 12px;display:flex;gap:6px}.task .st{width:52px;flex:none}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:4px 18px}
.muted{color:var(--muted)}
@media (max-width:1100px){.grid{grid-template-columns:1fr}.left,.bottom{grid-row:auto;grid-column:auto}}
</style>
</head>
<body>
<header>
  <h1><span>TaoChronos</span> · 发现工作台 Discovery Workspace</h1>
  <div class="q" id="question"></div>
  <div class="chips" id="chips"></div>
</header>
<div class="grid">
  <section class="panel left">
    <h2>候选假说 Hypotheses</h2><div id="hyps"></div>
    <h2>任务 Tasks</h2><div id="tasks"></div>
  </section>
  <section class="panel center">
    <div class="tabs" id="tabs"></div>
    <div class="view" id="v-graph"><svg id="graph" viewBox="0 0 900 560"></svg><div class="muted" style="font-size:12px">节点：术语（颜色=类别）；边：同一主张超边内共现 / 方剂化裁。点击左侧假说以高亮其术语。</div></div>
    <div class="view" id="v-timeline"><svg id="timeline" viewBox="0 0 900 420"></svg><div class="muted" style="font-size:12px"><span style="color:var(--ok)">●</span> 支持证据　<span style="color:var(--bad)">●</span> 反证　（横轴：成书年代；点击圆点查看原文）</div></div>
    <div class="view" id="v-evolution"></div>
    <div class="view report" id="v-report"></div>
    <div class="view" id="v-trace"><pre id="trace"></pre></div>
  </section>
  <section class="panel right">
    <h2>原文 · 异文 · 溯源 Source</h2><div id="source"><div class="section muted">点击证据查看原文。</div></div>
  </section>
  <section class="panel bottom">
    <h2 id="detail-title">假说详情 Hypothesis</h2><div id="detail"><div class="section muted">选择一个假说。</div></div>
  </section>
</div>
<script id="data" type="application/json">__TAOCHRONOS_DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KIND = {lost_knowledge:'失传知识',historical_testimony:'文本证词',lost_source:'佚书线索',concept_drift:'概念演变',formula_evolution:'方剂演化',renaming:'避讳改名',association_rule:'关联规则',hidden_association:'隐性关联',contradiction:'矛盾分析',cross_space_bridge:'跨空间桥接'};
const STATUS = {survived:'存活',expert_approved:'专家认可',proposed:'待审',needs_revision:'待修订',rejected:'被否决',expert_rejected:'专家否决',superseded:'已取代'};
const GATES = ['G0','G1','G2','G3','G4','G5','G6','G7','G8'];
const MARK = {pass:'✓',warn:'△',fail:'✗',pending:'…',not_applicable:'—'};
const COLORS = {symptom:'#c2410c',sign:'#c2410c',pulse:'#9a3412',tongue:'#9a3412',disease:'#7c3aed',pattern:'#6d28d9',formula:'#0f766e',herb:'#15803d',pathogenesis:'#b45309',etiology:'#a16207',treatment_principle:'#2563eb',treatment_method:'#1d4ed8',concept:'#64748b',condition:'#475569',organ:'#be185d'};
let selected = null;

$('question').textContent = D.question;
const m = D.metrics;
$('chips').innerHTML = [`会话 ${D.session}`, `画像 ${D.profile}`, `状态 ${D.status}`, `主张 ${m.claims}`, `证据 ${m.evidence_count}`,
  `反证 ${m.counter_evidence}`, `观察 ${m.observations}`, `假说 ${m.hypotheses}`, `存活率 ${m.hypothesis_survival ?? '—'}`,
  `智能体 ${m.agents_spawned}`, `工具调用 ${m.tool_calls}`, `模型调用 ${m.llm_calls}`].map(c => `<span class="chip">${esc(c)}</span>`).join('');

function renderHyps(){
  $('hyps').innerHTML = D.hypotheses.map((h, i) => `<div class="hyp" data-id="${h.id}">
    <div class="meta"><b>H${i+1}</b><span class="badge">${esc(KIND[h.kind]||h.kind)}</span><span class="s-${h.status}">${esc(STATUS[h.status]||h.status)}</span>
    <span>D=${h.d ?? '—'}</span><span>Elo ${Math.round(h.elo)}</span>${h.generation ? `<span>第${h.generation}代</span>` : ''}</div>
    <div class="t">${esc(h.statement)}</div></div>`).join('');
  document.querySelectorAll('.hyp').forEach(el => el.onclick = () => select(el.dataset.id));
}
function renderTasks(){
  let html = '', round = null;
  for (const t of D.tasks){
    if (t.round !== round){ round = t.round; html += `<div class="task muted"><b>第 ${round} 轮</b></div>`; }
    const cls = t.status === 'done' ? 'g-pass' : (t.status === 'failed' ? 'g-fail' : 'g-warn');
    html += `<div class="task" title="${esc(t.summary)}"><span class="st ${cls}">${esc(t.status)}</span><span>${esc(t.kind)} <span class="muted">← ${esc(t.role)}</span></span></div>`;
  }
  $('tasks').innerHTML = html;
}

const TABS = [['graph','知识网络'],['timeline','时间线'],['evolution','概念与方剂演化'],['report','发现报告'],['trace','智能体轨迹']];
$('tabs').innerHTML = TABS.map(([k, l]) => `<button data-k="${k}">${l}</button>`).join('');
function tab(k){ document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.k === k));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + k)); }
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => tab(b.dataset.k));

// ------------------------------------------------------------------ graph (seeded force layout)
function renderGraph(){
  const W = 900, H = 560, nodes = D.graph.nodes.map(n => ({...n})), idx = {};
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  nodes.forEach((n, i) => { idx[n.id] = i; n.x = W/2 + (rnd()-.5)*W*.8; n.y = H/2 + (rnd()-.5)*H*.8; n.vx = 0; n.vy = 0; });
  const links = D.graph.links.filter(l => l.source in idx && l.target in idx);
  for (let it = 0; it < 320; it++){
    for (let i = 0; i < nodes.length; i++) for (let j = i+1; j < nodes.length; j++){
      const a = nodes[i], b = nodes[j]; let dx = a.x-b.x, dy = a.y-b.y, d2 = dx*dx+dy*dy+.01, f = 1600/d2;
      a.vx += dx*f/Math.sqrt(d2); a.vy += dy*f/Math.sqrt(d2); b.vx -= dx*f/Math.sqrt(d2); b.vy -= dy*f/Math.sqrt(d2); }
    for (const l of links){ const a = nodes[idx[l.source]], b = nodes[idx[l.target]]; const dx = b.x-a.x, dy = b.y-a.y;
      const d = Math.sqrt(dx*dx+dy*dy)+.01, f = (d-70)*.02; a.vx += dx/d*f; a.vy += dy/d*f; b.vx -= dx/d*f; b.vy -= dy/d*f; }
    for (const n of nodes){ n.vx += (W/2-n.x)*.004; n.vy += (H/2-n.y)*.004; n.x += n.vx*.5; n.y += n.vy*.5; n.vx *= .6; n.vy *= .6;
      n.x = Math.max(20, Math.min(W-20, n.x)); n.y = Math.max(16, Math.min(H-16, n.y)); }
  }
  const svg = [];
  for (const l of links){ const a = nodes[idx[l.source]], b = nodes[idx[l.target]];
    svg.push(`<line class="glink" data-a="${esc(l.source)}" data-b="${esc(l.target)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke-width="${Math.min(4, .6+l.weight*.5)}"/>`); }
  for (const n of nodes){ const r = 4 + Math.min(9, Math.sqrt(n.weight)*2);
    svg.push(`<g class="gnode" data-id="${esc(n.id)}"><circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${COLORS[n.group]||'#888'}"><title>${esc(n.id)}</title></circle><text x="${n.x+r+2}" y="${n.y+4}">${esc(n.label)}</text></g>`); }
  $('graph').innerHTML = svg.join('');
}
function highlightGraph(terms){
  const set = new Set(terms || []);
  document.querySelectorAll('.gnode').forEach(g => g.classList.toggle('dim', set.size && !set.has(g.dataset.id)));
  document.querySelectorAll('.glink').forEach(l => l.classList.toggle('dim', set.size && !(set.has(l.dataset.a) || set.has(l.dataset.b))));
}

// ------------------------------------------------------------------ timeline
function renderTimeline(){
  const W = 900, rows = D.hypotheses.slice(0, 14), H = 40 + rows.length*26, x0 = 170, x1 = W-20;
  const years = Object.values(D.passages).map(p => p.year).filter(y => y !== null);
  const lo = Math.min(-300, ...years), hi = Math.max(1911, ...years), X = y => x0 + (y-lo)/(hi-lo)*(x1-x0);
  const out = [];
  for (const tick of [-200, 0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800]){
    if (tick < lo || tick > hi) continue;
    out.push(`<line x1="${X(tick)}" y1="20" x2="${X(tick)}" y2="${H-10}" stroke="var(--line)"/><text x="${X(tick)}" y="14" font-size="10" text-anchor="middle" fill="var(--muted)">${tick < 0 ? '前'+(-tick) : tick}</text>`);
  }
  rows.forEach((h, i) => { const y = 40 + i*26;
    out.push(`<text x="4" y="${y+4}" font-size="11" fill="var(--ink)">H${i+1} ${esc((KIND[h.kind]||h.kind))}</text><line x1="${x0}" y1="${y}" x2="${x1}" y2="${y}" stroke="var(--line)" stroke-dasharray="2 3"/>`);
    for (const [ids, color] of [[h.support, 'var(--ok)'], [h.counter, 'var(--bad)']]) for (const eid of ids){
      const e = D.evidence[eid], p = e && D.passages[e.passage_id]; if (!p || p.year === null) continue;
      out.push(`<circle cx="${X(p.year)}" cy="${y}" r="5" fill="${color}" style="cursor:pointer" onclick="showEvidence('${eid}')"><title>${esc(p.book)} ${esc(p.locator)} (${p.year})\n${esc(e.quote)}</title></circle>`); }
  });
  $('timeline').setAttribute('viewBox', `0 0 ${W} ${H}`); $('timeline').innerHTML = out.join('');
}

// ------------------------------------------------------------------ evolution
function renderEvolution(){
  const parts = [];
  for (const ev of D.evolution){
    if (ev.kind === 'concept_timeline'){
      parts.push(`<h3>概念演变：${esc(String(ev.term).split(':').pop())}</h3><table><tr><th>时期</th><th>用例</th><th>文献</th><th>主导义项</th></tr>` +
        ev.rows.map(r => `<tr><td>${esc(r.label)}</td><td>${r.occurrences}</td><td>${esc(r.books.join('、'))}</td><td>${esc(r.dominant_sense||'')}</td></tr>`).join('') +
        `</table><p>${esc(ev.narrative)}</p>`);
    } else if (ev.kind === 'formula_tree'){
      const label = id => id.split(':').pop();
      parts.push(`<h3>方剂谱系：${esc(ev.nodes.map(n => label(n.id)).join(' → '))}</h3><ul>` +
        ev.edges.map(e => `<li><b>${esc(label(e.from))}</b> → <b>${esc(label(e.to))}</b>　` +
          (e.added.length ? `加 ${esc(e.added.map(label).join('、'))}　` : '') + (e.removed.length ? `去 ${esc(e.removed.map(label).join('、'))}　` : '') +
          (e.substituted.length ? `易 ${esc(e.substituted.map(s => label(s.from)+'→'+label(s.to)).join('、'))}　` : '') +
          (e.renames.length ? `<span class="muted">改名 ${esc(e.renames.map(r => r.parent_surface+'→'+r.child_surface).join('、'))}</span>` : '') + `</li>`).join('') +
        `</ul><p>核心：${esc(ev.stable_core.map(label).join('、') || '—')}。${esc(ev.narrative)}</p>`);
    }
  }
  $('v-evolution').innerHTML = parts.join('') || '<p class="muted">本次研究没有概念或方剂演化观察。</p>';
}

// ------------------------------------------------------------------ source panel
function showEvidence(eid){
  const e = D.evidence[eid], p = e && D.passages[e.passage_id];
  if (!p){ $('source').innerHTML = `<div class="section">${esc(e ? e.quote : eid)}<div class="muted">${esc(e ? e.note : '')}</div></div>`; return; }
  const marks = []; for (let i = 0; i < p.text.length; i++) marks.push('');
  for (const c of p.contested) for (let i = c.start; i < c.end; i++) marks[i] += ' contest';
  let html = '';
  for (let i = 0; i < p.text.length; i++){
    const inEv = i >= e.start && i < e.end, cls = marks[i].trim();
    let ch = esc(p.text[i]); if (cls) ch = `<span class="${cls}">${ch}</span>`; if (inEv) ch = `<mark>${ch}</mark>`; html += ch;
  }
  const variants = p.variants.length ? `<div class="section"><h3>异文 Variants</h3>` + p.variants.map(v => `<div>「${esc(p.text.slice(v.start, v.end))}」→「${esc(v.reading)}」 <span class="muted">${esc(v.witness)} · ${esc(v.kind)}</span></div>`).join('') + `</div>` : '';
  const contested = p.contested.length ? `<div class="section"><h3>读法概率 Readings</h3>` + p.contested.map(c => c.options.map(o => `<div>「${esc(o.reading)}」 p=${o.probability} <span class="muted">${esc(o.witness)}</span></div>`).join('') + `<div class="muted">不确定 uncertain = ${c.uncertain}</div>`).join('') + `</div>` : '';
  const chain = `<div class="section"><h3>溯源链 Claim → Pixel</h3>` + p.chain.map(c => `<div>${esc(c.level)}：${c.available ? esc(String(c.label ?? c.id).slice(0, 60)) : '<span class="muted">（不可用）</span>'}</div>`).join('') + `</div>`;
  $('source').innerHTML = `<div class="kv"><b>《${esc(p.book)}》</b> ${esc(p.locator)} · ${esc(p.dynasty)} · ${p.year ?? '?'} · 校勘状态 ${esc(p.collation)} · 文献学置信 ${p.philological_confidence ?? '—'}</div>
    <div class="passage">${html}</div><div class="kv">证据 ${esc(eid)} · ${esc(e.stance)} · ${esc(e.method)}</div>${contested}${variants}${chain}`;
}

// ------------------------------------------------------------------ detail panel
function select(id){
  selected = D.hypotheses.find(h => h.id === id); if (!selected) return;
  document.querySelectorAll('.hyp').forEach(el => el.classList.toggle('sel', el.dataset.id === id));
  const h = selected, comp = h.components || {};
  const bars = ['E','N','R','T','F','A'].filter(k => k in comp).map(k => `<div class="bar"><span style="width:16px">${k}</span><i style="width:${Math.round(comp[k]*140)}px"></i>${comp[k].toFixed(2)}</div>`).join('');
  const gates = GATES.map(g => `<span class="g-${h.gates[g]||'pending'}">${g}${MARK[h.gates[g]]||'…'}</span>`).join('');
  const ev = (ids, cls) => ids.map(eid => { const e = D.evidence[eid], p = e && D.passages[e.passage_id];
    return `<div class="ev ${cls}" onclick="showEvidence('${eid}')">${p ? `《${esc(p.book)}》${esc(p.locator)} ` : ''}「${esc(e.quote)}」</div>`; }).join('');
  const objections = h.objections.map(o => `<div class="ev ${o.resolved ? 'context' : (o.severity === 'critical' ? 'contra' : '')}">[${esc(o.severity)}/${esc(o.check)}]${o.resolved ? '（已解决）' : ''} ${esc(o.detail)}</div>`).join('');
  const conf = Object.entries(h.confidence).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');
  $('detail-title').textContent = `假说详情 · ${h.id}`;
  $('detail').innerHTML = `<div class="section"><div class="meta"><span class="badge">${esc(KIND[h.kind]||h.kind)}</span><span class="s-${h.status}">${esc(STATUS[h.status]||h.status)}</span>
    <span>知识空间 ${esc(h.space)}</span><span>文献学风险 ${esc(h.philological_risk)}</span><span>时代错置风险 ${esc(h.anachronism_risk)}</span></div>
    <p style="font-size:15px">${esc(h.statement)}</p>${h.revision_note ? `<p class="muted">修订：${esc(h.revision_note)}</p>` : ''}</div>
    <div class="cols"><div class="section"><h3>发现分数 D = ${h.d ?? '—'}</h3>${bars}<h3>门控 Gates</h3><div class="gates">${gates}</div>
      <h3>置信度（学者视图）</h3><table>${conf}</table></div>
    <div class="section"><h3>支持证据 Support</h3>${ev(h.support, '') || '<span class="muted">—</span>'}<h3>反证 Counter-evidence</h3>${ev(h.counter, 'contra') || '<span class="muted">—</span>'}</div>
    <div class="section"><h3>异议 Objections（${esc(h.verdict || '未审')}）</h3>${objections || '<span class="muted">—</span>'}
      <h3>替代解释</h3>${h.alternatives.map(a => `<div class="ev context">${esc(a)}</div>`).join('')}<h3>可检验预测</h3><div>${esc(h.prediction)}</div></div></div>`;
  highlightGraph(h.terms);
  if (h.support.length) showEvidence(h.support[0]);
}

renderHyps(); renderTasks(); renderGraph(); renderTimeline(); renderEvolution();
$('v-report').innerHTML = D.report_html; $('trace').textContent = D.agent_tree;
tab('graph'); if (D.hypotheses.length) select(D.hypotheses[0].id);
</script>
</body>
</html>
"""
