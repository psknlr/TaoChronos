// What a visitor reads of the model, in plain words: the names it works with inside — its tools and their parameters
// and fields, the codes of the discovery tracks, gates and skills, the local service's commands, files and settings —
// are replaced before anything is shown (the answer, the thinking, the tool steps) or leaves the page (a copy, an
// export, the owner's record of the turn).  The model is told the same (src/taochronos/chat/prompt.py, 不外露内部细节);
// this holds when it forgets.  A citation's mark [[…]] is the page's own and stays as it is, as do links; inside a code
// block only these names are replaced, not every identifier.  (The tools run in the visitor's browser, so their names
// are in the page's code and requests: what is kept from the visitor is the answer that names them.)

/** Each tool by its catalog name (on the wire, `__` for `.`): the plain words the page shows for it. */
export const TOOL_WORDS = {
  "classics.search": "古籍检索", "classics.get_passage": "原文细读", "classics.list_books": "书目", "classics.canon": "要籍目录",
  "classics.lineage": "知识谱系",
  "kg.term": "术语词条", "kg.claims": "主张查询", "kg.neighbors": "共现术语", "kg.extract_claims": "主张抽取",
  "analysis.lost_knowledge": "失传关联", "analysis.concept_drift": "概念漂移", "analysis.formula_evolution": "方剂演化",
  "analysis.association_rules": "关联规则", "analysis.link_prediction": "隐含关联", "analysis.contradictions": "矛盾发现",
  "analysis.missing_sources": "佚书线索", "analysis.communities": "症证方群落", "analysis.temporal_profile": "时代分布",
  "study.formula": "方源考", "study.herb": "药性源流", "study.term": "术语源流", "study.concordance": "经文互见",
  "study.commentaries": "集注比较", "study.translate": "释义与今译", "study.network": "方证网络", "study.argument": "医理论证",
  "study.authorship": "作者归属", "study.cards": "学习卡片", "study.cases": "医案", "study.chain": "传播链",
  "study.citations": "引书与引人", "study.clause": "条文结构", "study.dating": "断代证据", "study.disputes": "争议挖掘",
  "study.entities": "实体识别", "study.fragments": "佚书辑佚", "study.glosses": "训诂", "study.layers": "文本地层",
  "study.metrology": "历代度量衡", "study.names": "名称", "study.pairs": "配伍规律", "study.places": "地域",
  "study.punctuate": "句读", "study.reading": "阅读门径", "study.reuse": "语义复用", "study.schools": "学派",
  "study.senses": "语义演变", "study.stemma": "版本谱系", "study.taboo": "避讳断代", "study.trajectories": "医案轨迹",
  "study.transmission": "思想传播", "study.variants": "异文校勘", "study.witnesses": "版本与影像见证",
  "study.compare": "方剂比较", "study.family": "类方", "study.usage": "药物用量与配伍", "study.properties": "性味归经对照",
  "study.incompat": "配伍禁忌", "study.protocol": "研究方案设计",
  "study.casefind": "医案检索", "study.similar": "类案", "study.case": "医案详解", "study.casecompare": "医家与时代比较",
  "study.modifications": "随证加减", "study.treatments": "同病异治·异病同治",
  "philology.assess_passage": "文献评估", "philology.collate": "校勘", "philology.inspect_page": "页面溯源",
  "philology.normalize": "异体规范", "vision.layout": "版面理解", "vision.compare": "OCR 核对",
  "validation.verify_quote": "引文核验", "validation.gates": "门控核验", "validation.provenance_chain": "溯源链",
  "audit.claim": "论断审计", "graph.evidence": "证据图谱",
  "bridge.phenotype": "古代表型", "bridge.map": "古今映射", "bridge.reverse": "今病溯古",
  "modern.safety": "安全提示", "modern.search": "现代证据", "literature.modern_evidence": "现代研究证据", "rwd.ask": "真实世界数据",
  "research.run_code": "研究脚本",
  "mydata.list": "我的资料", "mydata.read": "资料阅读", "mydata.search": "资料检索", "mydata.describe": "描述统计",
  "mydata.compare": "组间比较", "mydata.prescriptions": "处方用药分析",
  taochronos_research: "发现研究", taochronos_session: "研究会话", taochronos_ask: "技能工作流",
  taochronos_catalog: "工具目录", taochronos_call: "调用工具",
};
const FAMILY_WORDS = { classics: "检索", kg: "知识", analysis: "发现", study: "治学", philology: "文献", vision: "文献",
  validation: "核验", audit: "核验", graph: "核验", bridge: "古今", modern: "现代", literature: "现代", rwd: "现代", research: "代码",
  mydata: "我的资料" };
const FIELD_WORDS = { passage_id: "段落编号", book_id: "录本编号", session_id: "研究会话编号", claim_id: "主张编号",
  hypothesis_id: "假说编号", evidence_id: "证据编号", work_id: "书目编号" };
// the labels the tools grade with — an audit's verdict, who asserts a link, modern evidence by its design and by what
// it claims (src/taochronos/protocol: assertions.py, modern.py) — as a reader says them
const LABEL_WORDS = {
  SUPPORTED: "有据", PARTIALLY_SUPPORTED: "部分有据", CONTESTED: "有争议", INSUFFICIENT_EVIDENCE: "证据不足", UNSUPPORTED: "无据",
  SOURCE_ASSERTED: "原文所言", SCHOLAR_INTERPRETED: "注家解释", MODEL_EXTRACTED: "模型抽取", MODEL_INFERRED: "模型推断",
  MODERN_EVIDENCE_SUPPORTED: "现代证据支持", HYPOTHESIS: "假说",
  systematic_review: "系统综述", case_control: "病例对照研究", cross_sectional: "横断面研究", case_series: "病例系列",
  case_report: "病例报告", narrative_review: "叙述性综述", in_vitro: "体外研究", in_silico: "计算预测", expert_opinion: "专家意见",
  human_efficacy: "人体疗效", human_association: "人群关联", tcm_semantic: "中医语义",
};
const TRACKS = ["失传关联", "概念漂移", "方剂演化", "关联规则与隐含关联", "矛盾"]; // D1–D5
const GATES = ["来源", "录文", "文献", "语义", "主张溯源", "跨源互证", "证伪", "专家核验", "生物医学证据"]; // G0–G8

/** A tool as the page names it: its plain words, else its family's (a tool this page does not know yet). */
export function toolWord(name) {
  if (!name || name === "…") return name || "…";
  const key = String(name).replace(/__/g, ".");
  const family = FAMILY_WORDS[key.split(".")[0]];
  return TOOL_WORDS[key] || TOOL_WORDS[name] || (family ? `${family}工具` : "工具");
}

const PREFIXES = Object.keys(FAMILY_WORDS).join("|");
const DASH = String.raw`\s*(?:[–—~-]|到|至)\s*`;
const CODE = String.raw`[DGST]\d{1,2}(?:${DASH}[DGST]?\d{1,2})?`;
const track = (n) => TRACKS[Number(n) - 1];

// [pattern, replacement]: in this order; a replacement function gets the match and its groups.  `lead` keeps the
// character before a name, which only marks where the name starts.
const NAMES = [
  // the project's files, first (classics.py is a file, not a tool)
  [/(^|[^\w/.-])((?:src|web|docs|cloud|relay|security|agents|profiles|domains|corpus|skills|evals|tests|scripts|paper|data)\/[\w./-]*\w)/g,
    (m, lead) => lead + put("内部文件")],
  [/(^|[^\w/.-])[\w-]+\.(?:py|mjs|toml|ya?ml|sql|sh)\b/g, (m, lead) => lead + put("内部文件")],
  // the local service and its commands: taochronos serve …, python -m taochronos …, pip install taochronos
  [/\b(?:python3?\s+-m\s+|pip3?\s+install\s+(?:-e\s+)?)taochronos\b(?:\[[\w,]*\])?(?:\s+(?:--?[a-z][\w-]*|[a-z0-9][\w.:/=-]*))*/g, "本地服务"],
  [/\btaochronos(?:\s+(?:--?[a-z][\w-]*(?:=[^\s`，。；、）)]+)?|[a-z0-9][\w.:/-]*))+/g, "本地服务"],
  [/\btaochronos_(research|session|ask|catalog|call)\b/g, (m) => put(TOOL_WORDS[m])],
  [/\btaochronos(?:[._][a-z]\w*)+/g, "内部模块"],
  // tools, as the model calls them (classics__search) and as the catalog names them (classics.search)
  [/\b([a-z][a-z0-9]*)__([a-z][a-z0-9_]*)\b/g, (m, a, b) => put(toolWord(`${a}.${b}`))],
  [new RegExp(String.raw`(^|[^\w.@-])((?:${PREFIXES})\.[a-z][a-z0-9_]*)(?![\w@-]|\.[a-z])`, "g"), (m, lead, name) => lead + put(toolWord(name))],
  // fields of the tools' results
  [/\b(passage_id|book_id|session_id|claim_id|hypothesis_id|evidence_id|work_id)s?\b/g, (m, f) => put(FIELD_WORDS[f])],
  // the tools' grading labels
  [new RegExp(String.raw`\b(?:${Object.keys(LABEL_WORDS).join("|")})\b`, "g"), (m) => put(LABEL_WORDS[m])],
  // codes: of a step in parentheses — （G7）、(S15)、(AMBE S11–S12)、(T10) — gone; the discovery tracks D1–D5, the gates
  // G0–G8 and the skills S01–S15 told by what they are
  [new RegExp(String.raw`\s*[（(]\s*(?:AMBE\s*)?${CODE}(?:\s*[,，、/]\s*${CODE})*\s*[）)]`, "g"), ""],
  [new RegExp(String.raw`\bD[1-5]${DASH}D?[1-5]\b`, "g"), "知识发现"],
  [new RegExp(String.raw`(?:门控\s*)?\bG[0-8]${DASH}G?[0-8]\b(?:\s*门控)?`, "g"), "各级门控"],
  [new RegExp(String.raw`(?:技能\s*)?\bS(?:0[1-9]|1[0-5])${DASH}S?(?:0[1-9]|1[0-5])\b`, "g"), "各项技能"],
  [/\bD[1-5](?:\s*(?:[、，,和与及])\s*D[1-5])+\b/g, (m) => put(m.replace(/D([1-5])/g, (x, n) => track(n)).replace(/\s+/g, ""))],
  [/\bD([1-5])\s*(?=失传|概念|方剂|关联|隐含|矛盾)/g, ""],
  [/\bD([1-5])(?=\s*(?:分析|轨道|发现|任务|模块))/g, (m, n) => put(track(n))],
  [/\bG([0-8])(?=\s*(?:门控|关口|核验))/g, (m, n) => put(GATES[n])],
  [/(门控\s*)G([0-8])\b/g, (m, lead, n) => lead + put(GATES[n])],
  [/(?:技能\s*)?\bS(?:0[1-9]|1[0-5])\b/g, "相应技能"],
  [/\bAMBE\b/g, "古今桥接"],
  [/\bV2\s*(?=技能|工作流)/g, ""],
  [/\bCode Mode\b/gi, "代码研究"],
];
// outside code blocks: any setting (UPPER_SNAKE) and any identifier (snake_case) is one of the page's own
const IDENTIFIERS = [
  [/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, "内部配置"],
  [/(^|[^\w./@-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w@-]|\.[a-z])(?:\s*(?:参数|字段))?/g, (m, lead) => lead + put("相应参数")],
];
// kept as they are: a citation's mark, a link, a link's target
const KEEP = /\[\[[^\]\n]*\]\]|https?:\/\/[^\s<>()（）「」"]+|\]\([^)\s]+\)/g;
const HELD = /\uE000(\d+)\uE001/g;

// plain words put in are marked while the text is worked on, so that the spaces an English name stood between are
// dropped where the words now meet Chinese (附 passage_id 以便 → 附段落编号以便)
const IN = "\uE002";
const OUT = "\uE003";
const put = (words) => (words ? IN + words + OUT : words);
const CJK = "\u3000-\u303f\u3400-\u9fff\uff00-\uffef";
const SPACED_BEFORE = new RegExp(`([${CJK}])[ \\t]+${IN}`, "g");
const SPACED_AFTER = new RegExp(`${OUT}[ \\t]+([${CJK}])`, "g");

function apply(text, rules, hit) {
  for (const [re, to] of rules) {
    text = text.replace(re, (...args) => {
      const out = typeof to === "function" ? to(...args) : put(to);
      if (out !== args[0]) hit();
      return out;
    });
  }
  return text;
}

/**
 * The text with the model's inside names told in plain words: {text, hits}.  streaming: the text is still arriving, and
 * a word at its end, still incomplete, is held back until it is whole (no half of a name is ever shown).
 */
export function scrub(text, { streaming = false } = {}) {
  let s = String(text ?? "");
  if (streaming) s = s.replace(/[A-Za-z0-9_.\-/`[\]–—~]+$/, "");
  let hits = 0;
  const hit = () => { hits++; };
  const kept = [];
  s = s.replace(KEEP, (m) => `\uE000${kept.push(m) - 1}\uE001`);
  // code blocks (``` or ~~~) take the names only; the prose takes the names, then any identifier
  let fence = null;
  const prose = [];
  const out = [];
  const flush = () => { if (prose.length) { out.push(scrubProse(prose.join("\n"), hit)); prose.length = 0; } };
  for (const line of s.split("\n")) {
    const mark = /^\s*(`{3,}|~{3,})/.exec(line)?.[1];
    if (fence) {
      out.push(apply(line, NAMES, hit));
      if (mark && mark[0] === fence[0] && mark.length >= fence.length) fence = null;
    } else if (mark) {
      flush();
      fence = mark;
      out.push(line);
    } else prose.push(line);
  }
  flush();
  const told = out.join("\n").replace(SPACED_BEFORE, `$1${IN}`).replace(SPACED_AFTER, `${OUT}$1`).replace(/[\uE002\uE003]/g, "");
  return { text: told.replace(HELD, (m, i) => kept[Number(i)]), hits };
}

function scrubProse(text, hit) {
  // a code span that holds an inside name becomes plain words, without the code marks
  text = text.replace(/`([^`\n]+)`/g, (m, inner) => {
    let n = 0;
    const told = apply(apply(inner, NAMES, () => n++), IDENTIFIERS, () => n++);
    if (!n) return m;
    for (let k = 0; k < n; k++) hit();
    return told.trim();
  });
  return apply(apply(text, NAMES, hit), IDENTIFIERS, hit);
}

/** The text as a visitor may read it (scrub's text). */
export const redact = (text, opts) => scrub(text, opts).text;
