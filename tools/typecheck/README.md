# The type checker

`tsc` reads the repository's JavaScript as it is — the page (`web/js`), its module workers, the two Cloudflare Workers
and the code they share (`security/`) — and writes nothing: no build step, no emitted file, no source map.  The types
are JSDoc comments in the files themselves, and declaration files here (`types/`) for what reaches the page from
elsewhere.  A file is checked once its first line is `// @ts-check`, and then under `strict`; the rest is read only for
what it exports, and never reported on.

## Running it

```bash
(cd tools/typecheck && npm ci --ignore-scripts --no-audit --no-fund)
tools/typecheck/node_modules/.bin/tsc -p tools/typecheck/tsconfig.web.json      # the page (lib DOM)
tools/typecheck/node_modules/.bin/tsc -p tools/typecheck/tsconfig.worker.json   # its module workers (lib WebWorker)
tools/typecheck/node_modules/.bin/tsc -p tools/typecheck/tsconfig.workers.json  # the Workers (workerd)
```

CI runs exactly this (`.github/workflows/ci.yml`, job `typecheck`): the install takes under a second, the three
programs about four seconds in all.  `typescript` and `@cloudflare/workers-types` are pinned exactly, with their sha512
in the lockfile (`tests/test_supply_chain.py`); Dependabot proposes the next in a pull request of their own (a new
TypeScript major, which reads unannotated JavaScript otherwise, is left to a change of its own), and the audit workflow
reads the lockfile each week.  The Workers' types stay within the range `wrangler` (relay/, cloud/site/) names as its
peer (`^5.20261023.1` for 4.153.0).

## Opting a file in

1. Make `// @ts-check` its first line and run its program: tsc now reports the file, under strict.
2. Type it in comments only: `@param`, `@returns`, `@type`, `@typedef`, `@template`; a cast, `/** @type {T} */ (expr)`;
   `/** @satisfies {T} */ ({ … })` for a message posted to a worker, which checks its keys.  No statement changes: the
   file that ships is the same program, comments and parentheses aside.  Where tsc cannot follow the code (a variable
   set in a closure, a vendored module), a cast says what the code knows, with a comment when it is not plain.
3. Types from elsewhere come in as a comment, which no browser follows:
   `/** @import { RuntimeInfo } from "../../tools/typecheck/types/runtime" */`.

Opted in: `limits.js`, `store.js`, `providers.js`, `runtime.js`, `worker.js` (with the part of Pyodide's API it uses
declared in it), `taocore.js`, `unpack.js`, `unpack-worker.js`, `brand.js`, `diet/prompt.js` and the fifteen
`i18n-*.js` tables (where tsc finds a key written twice).  The generated modules
(`diet/dishes.js`, `diet/medicinal-data.js`, `cloud/site/src/backup/tables.js`) are clean but left out: their tests
compare them byte for byte with what their generators write, and checking a megabyte of literals costs a second for
nothing tsc could find in them.  `worker.js` is a root of `tsconfig.worker.json`: it and what it imports are checked
there under a worker's globals.

## Three programs, and `types/`

A page and a worker have different globals — a worker has no `document`, `localStorage` or `window` — so `lib: DOM` and
`lib: WebWorker` are separate programs: in one, their declarations conflict (33 errors, unless the libraries go
unchecked), and `document` in a worker would go unnoticed.  A module both sides import (`i18n.js`, `unpack.js`) is
checked under both once it opts in.  The Workers run on workerd: `@cloudflare/workers-types` gives its globals and
`cloudflare:workers`, and one program for both Workers checks `security/` once.

`types/runtime.d.ts` is what crosses into the page: the chat runtime's answers (the shapes `src/taochronos/chat`
writes) and the messages between `runtime.js`, `worker.js` and `unpack-worker.js`.  It imports no page module, so
that worker code importing it brings no page code into `tsconfig.worker.json`.  A field the Python renames is renamed
there, and tsc then names every place the page still reads the old one.  Declaration files are checked too
(`skipDefaultLibCheck`, not `skipLibCheck`, which would skip them).

Nothing here is under `web/`: the site build copies `web/` whole, so a declaration file or a `tsconfig` there would be
published.  An editor finds a `tsconfig` only in or above a file's own directory, so it reads `web/js` with its own
defaults: it shows the types, and the strict errors come from the commands above.

## Why JSDoc, not `.ts`

The same checking reaches the same files either way.  With JSDoc alone, and no statement changed, `runtime.js` went
from 111 strict errors to none and `limits.js` from 28; of 18 bugs seeded into the opted-in files (a misspelt RPC
method, a camelCase wire key, a misread job field, a misspelt worker event, arguments swapped…) the check fails on 17:
the one it misses is a wrong key in an object handed to `JSON.stringify`, which takes any value.  What `.ts` would add
is a build: the site ships `web/` as it is (`taochronos web build` copies it, and its audit fails a file that is
neither there nor generated), and its policy forbids `*.map` (`distribution-policy.yaml`), so the browser would run
transpiled code with no way back to the source.  The Workers could run TypeScript without a build step (wrangler
bundles it), but would gain syntax only, and their tests import them by `.js` path.
