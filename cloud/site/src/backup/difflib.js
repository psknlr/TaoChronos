// difflib.SequenceMatcher (autojunk=False, no junk), as philology.collate uses it: the same longest matches, hence the
// same opcodes, over sequences of code points.

export function opcodes(a, b) {
  const A = Array.from(a);
  const B = Array.from(b);
  const b2j = new Map();
  B.forEach((ch, j) => {
    if (!b2j.has(ch)) b2j.set(ch, []);
    b2j.get(ch).push(j);
  });

  // find_longest_match(alo, ahi, blo, bhi): the longest block, the earliest in a, then in b
  const longest = (alo, ahi, blo, bhi) => {
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      for (const j of b2j.get(A[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) {
          besti = i - k + 1;
          bestj = j - k + 1;
          bestsize = k;
        }
      }
      j2len = newj2len;
    }
    // no junk: the extension loops of the original change nothing
    return [besti, bestj, bestsize];
  };

  // get_matching_blocks
  const queue = [[0, A.length, 0, B.length]];
  const blocks = [];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = longest(alo, ahi, blo, bhi);
    if (k) {
      blocks.push([i, j, k]);
      if (alo < i && blo < j) queue.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
    }
  }
  blocks.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]);
  // collapse adjacent blocks
  const merged = [];
  let [i1, j1, k1] = [0, 0, 0];
  for (const [i2, j2, k2] of blocks) {
    if (i1 + k1 === i2 && j1 + k1 === j2) k1 += k2;
    else {
      if (k1) merged.push([i1, j1, k1]);
      [i1, j1, k1] = [i2, j2, k2];
    }
  }
  if (k1) merged.push([i1, j1, k1]);
  merged.push([A.length, B.length, 0]);

  // get_opcodes
  const ops = [];
  let i = 0;
  let j = 0;
  for (const [ai, bj, size] of merged) {
    let tag = "";
    if (i < ai && j < bj) tag = "replace";
    else if (i < ai) tag = "delete";
    else if (j < bj) tag = "insert";
    if (tag) ops.push([tag, i, ai, j, bj]);
    i = ai + size;
    j = bj + size;
    if (size) ops.push(["equal", ai, i, bj, j]);
  }
  return { ops, A, B };
}

/** PhilologyService.collate: the non-equal operations, with their text and spans. */
export function collate(a, b) {
  const { ops, A, B } = opcodes(a, b);
  return ops.filter(([tag]) => tag !== "equal").map(([op, i1, i2, j1, j2]) => ({
    op, a: A.slice(i1, i2).join(""), b: B.slice(j1, j2).join(""), a_span: [i1, i2], b_span: [j1, j2] }));
}
