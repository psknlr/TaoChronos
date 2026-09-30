// The lexicon (plugins/classics/domain.py, Lexicon), read from D1 a first character at a time: `lex` holds, for every
// first character, {surface: [entry …]} with each surface's entries already in lookup order (by category rank) and the
// synonym kind the surface has for each.  An entry is the LexEntry without its defaults ({id, term, cat, aliases …}).

const MAX_LEN = 9; // the longest surface (Lexicon.max_len on the full-corpus lexicon: checked by the tests)

export class Lexicon {
  constructor(corpus) {
    this.corpus = corpus;
    this.buckets = new Map(); // first character → {surface: [entry …]}
  }

  /** Load the buckets of these first characters (one query for all that are not loaded yet). */
  async load(chars) {
    const want = [...new Set([...chars].filter((c) => !this.buckets.has(c)))];
    if (!want.length) return;
    const rows = await this.corpus.all(0, "SELECT k, v FROM lex WHERE k IN (SELECT value FROM json_each(?))", [JSON.stringify(want)]);
    for (const c of want) this.buckets.set(c, {});
    for (const r of rows) this.buckets.set(r.k, JSON.parse(r.v));
  }

  /** Load what `match` needs for a text: the bucket of every character in it. */
  async loadText(text) {
    await this.load([...text]);
  }

  /** [{entry, kind}] for a surface, in lookup order (its bucket must be loaded). */
  lookup(surface) {
    if (!surface) return [];
    const first = String.fromCodePoint(surface.codePointAt(0));
    const hits = this.buckets.get(first)?.[surface] || [];
    return hits.map((e) => ({ entry: e, kind: e.sk || null }));
  }

  /** Lexicon.entry: by term id (formula:桂枝汤), found in the bucket of its term's first character. */
  entry(termId) {
    const i = termId.indexOf(":");
    if (i < 0) return null;
    const term = termId.slice(i + 1);
    return this.lookup(term).map((x) => x.entry).find((e) => e.id === termId) || null;
  }

  /** The buckets an id or a surface needs. */
  async loadIds(values) {
    await this.load(values.filter(Boolean).map((v) => {
      const s = v.includes(":") ? v.slice(v.indexOf(":") + 1) : v;
      return s ? String.fromCodePoint(s.codePointAt(0)) : "";
    }).filter(Boolean));
  }

  /** Lexicon.resolve: an entry by id, else the first of a surface's entries (of a category, if given). */
  resolve(surfaceOrId, category = null) {
    const byId = surfaceOrId.includes(":") ? this.entry(surfaceOrId) : null;
    if (byId) return byId;
    for (const { entry } of this.lookup(surfaceOrId)) if (category === null || entry.cat === category) return entry;
    return null;
  }

  canonical(surface, category = null) {
    return this.resolve(surface, category)?.id ?? null;
  }

  /** Lexicon.match: longest-first, left to right on (already normalised) text: [{entry, surface, start, end, kind, weak}]
   * (start and end in code points). */
  match(text, { includeWeak = true } = {}) {
    const cps = [...text];
    const out = [];
    let i = 0;
    while (i < cps.length) {
      let found = null;
      for (let len = Math.min(MAX_LEN, cps.length - i); len > 0; len--) {
        const surface = cps.slice(i, i + len).join("");
        const cands = this.lookup(surface);
        if (cands.length) {
          const { entry, kind } = cands[0];
          found = { entry, surface, start: i, end: i + len, kind, weak: Boolean(entry.weak) && len === 1 };
          break;
        }
      }
      if (!found) {
        i++;
        continue;
      }
      if (includeWeak || !found.weak) out.push(found);
      i = found.end;
    }
    return out;
  }
}

/** LexEntry.surfaces(): the term, its aliases, its synonyms. */
export const surfaces = (e) => [e.term, ...(e.aliases || []), ...Object.keys(e.synonyms || {})];

/** The entry as kg.term shows it. */
export const entryView = (e) => ({ term_id: e.id, category: e.cat, aliases: e.aliases || [], synonyms: e.synonyms || {},
  polarity: e.polarity || {}, components: e.components || [], broader: e.broader || [], related: e.related || [] });
