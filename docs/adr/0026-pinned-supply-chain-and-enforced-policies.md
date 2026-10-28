# ADR 0026 — A pinned supply chain, and the policies enforced: remediation of the security assessment of 2026-10-26

**Status:** accepted · 2026-10-28 · amends [ADR 0018](0018-sentinel-and-edge-rules.md) (the sentinel's mode, the page's
Content-Security-Policy) and [ADR 0016](0016-site-and-full-corpus-on-cloudflare.md) (how the Workers and the image are built)

## Context

A security assessment on 2026-10-26 (33 low-impact requests to chat.impf.ai and chat-api.impf.ai, the repository at
`3197ebc`, the dependencies matched against the public OSV, GitHub Actions and PSF databases) found no authorization
bypass: the protected endpoints refused missing and wrong tokens, foreign and `null` origins were refused, `.env` was
refused, http went to https.  It found:

* **P1, the deployment toolchain.**  The workflows ran `npx --yes wrangler@4.142.0`, whose tree resolved to undici
  7.29.0 and sharp 0.35.4: 14 distinct advisories, 4 high (among them a TLS certificate check dropped by undici's
  `BalancedPool`, and code execution through sharp's librsvg).  npx resolves the tree afresh on each run, and runs its
  install scripts, in the steps that hold the Cloudflare token.
* **P1, a conditional Python risk.**  With every extra installed, filelock 3.32.7 (through litellm) had
  CVE-2026-112940 (high: `ReadWriteLock` over a directory another local user can write) and two low, Windows-only
  advisories; the fix, 4.2.1, is outside litellm's `filelock<4.0`.
* **P2, the page's policy reported only.**  `Content-Security-Policy-Report-Only` without an enforced policy.
* **P2, versions not pinned.**  No Python lockfiles; `python:3.12-slim` by its mutable tag; lower bounds that let in
  releases with advisories (five of seven); every Action by a mutable major tag.
* **Observations.**  The relay's Origin allowlist is not an identity for a non-browser client; `SENTINEL = "observe"`.

## Decision

1. **Each Worker deploys with the wrangler its lockfile names.**  `relay/`, `cloud/site/` and `cloud/corpus/` each have
   `wrangler` 4.153.0 as an exact devDependency and a `package-lock.json` (some 90 packages, each with its registry URL
   and sha512): undici 7.30.1, sharp 0.35.5, `npm audit` clean.  The workflows install it with
   `npm ci --ignore-scripts` in a step that holds no secret (`deploy.sh` does the same), and run it as
   `npx --no -- wrangler`, which runs the installed copy and fails rather than fetch another.  Install scripts are not
   needed: `wrangler deploy --dry-run` bundles all three Workers from such an install.
2. **Every Action is pinned to the commit of its release** (`@<sha> # v4.4.0`), the same majors as before; a checkout
   whose job pushes nothing drops the token (`persist-credentials: false`: 15 of the 19; the 4 that commit logs keep
   it), so a package a job runs cannot take it; `ci.yml` gets `permissions: contents: read`.  Dependabot (`.github/dependabot.yml`) proposes the next
   commits, the Workers' lockfiles and the image's digest, weekly and grouped.
3. **Python comes from hashed lockfiles** ([requirements/README.md](../../requirements/README.md)): `runtime`, `build`,
   `dev`, `litellm`, `ingest` and `audit`, universal (every platform, Python 3.11 and up), each package pinned with the
   sha256 of its files, compiled by `requirements/lock.sh` (uv).  Every workflow and the image install with
   `pip install --require-hashes`, then the project with `--no-deps --no-build-isolation`, so the build too runs on
   hashed packages.  The lower bounds in `pyproject.toml` move to the first release from which no advisory applies
   (setuptools 84.1.0, wheel 0.46.2, litellm 1.103.1, pytest 9.0.3, pyarrow 23.0.1, pypdf 6.21.2).
   **filelock** is held at **3.20.3** (`requirements/constraints.in`): every release from 3.20.4 to 4.2.0 has the three
   advisories, every one before 3.20.3 has two others, and 3.20.3 satisfies litellm's range — a fix inside the
   dependencies' own constraints, not an override of them.  Nothing in this project or its LiteLLM tree uses
   `ReadWriteLock`, so the high one was not reachable here.
4. **The image** is built on `python:3.12-slim` by digest (Python 3.12.16), from `requirements/build.txt` and
   `runtime.txt`, drops setuptools, wheel and packaging once built, and runs as uid 10001: the server writes only
   `/srv/data` (sessions, jobs, the caches beside the store) and its home's YAML cache, never the code.  Checked without
   Docker by serving the repository's fixture corpus, prepared as root, as an unprivileged user over a root-owned
   install: info, a tool call and a research run answered, nothing written outside those two places.  The image's
   version now includes the two lockfiles.
5. **The page's policy is enforced where it protects** (`CSP` in `cloud/site/wrangler.toml`): `script-src` (the two
   hashed inline scripts, the site's files, jsDelivr's `/npm/` files — the Anthropic SDK and its imports, no longer
   `/gh/` — and Cloudflare's beacon; no eval), `object-src 'none'`, `base-uri 'none'`, and the ways out —
   `connect-src`, `img-src`, `worker-src`, `form-action`, `frame-ancestors`.  The whole policy stays reported
   (`CSP_REPORT_ONLY`).  Styles, fonts, media and frames are not enforced: of the 144 reports from 2026-10-06 to 10-28,
   those were where browser extensions and in-app browsers put their own (a translator's `<style>`, an icon font from
   alicdn or doubao, DingTalk's bridge `<iframe>`), and refusing them would cost visitors their extensions without
   protecting the page.  Of the 13 reports under the enforced directives none came from the page's code: 5 extensions
   (one an in-app browser's bridge script), 8 Cloudflare's beacon in a few browsers.  In Chromium, against the build
   served by the Worker with these headers, the pages, the settings, a turn through the default service, the English
   page and the SDK's import drew no violation; an inline script and an outside image injected into the page were both
   refused and the page worked on.  The sentinel now keeps a refused (`enforce`) report apart from a reported one.
6. **The sentinel enforces** (`SENTINEL = "enforce"` in both Workers): ADR 0018's condition — two weeks of `observe`
   with no genuine visitor among the `shadow` events — held.  In 22 days there were 7, all scanners: every request of
   theirs a 404 (10 to 671 of them), most from hosting networks (UCLOUD in Hong Kong, a network in Changchun, Anthropic's
   egress probing traversal paths), none with a browser's Sec-Fetch headers.
7. **The pins are audited every week and on every change** (`.github/workflows/audit.yml`): pip-audit, from its own
   hashed lockfile, reads every Python lockfile with the platform markers taken off (a Windows-only pin is read too);
   `npm audit` reads each Worker's.  `tests/test_supply_chain.py` keeps all of the above from coming undone: an Action
   on a tag, a checkout keeping its token, a `pip install` outside the lockfiles, a lower bound back below its floor,
   filelock back in its advisories' range, a wrangler outside a lockfile or installed with its scripts, the image by tag
   or as root, a lockfile missing from the image's version.

## Not done here

* **An identity for the relay's clients.**  Origin is only a browser's word; the edge rule `tc-relay-origin`, the
  per-address quotas and the sentinel bound what a non-browser client costs, and the assessment found no bypass of
  them.  A server-checked guest session (a Turnstile challenge once per visit, a short-lived signed token, per-session
  quotas) is [ADR 0023](0023-workers-paid.md)'s first item "not done": it needs a Turnstile site key and secret from the
  owner, and the page's policy opened to `challenges.cloudflare.com`.
* **The workers' policies** (`cloud/site/_headers`) stay reported: enforced, the in-browser runtime would stop on the
  engines that do not know `'wasm-unsafe-eval'` (Chromium < 97, Firefox < 102, Safari < 16, some in-app browsers).
* **Inventories of production.**  The image is now defined by a digest and hashed lockfiles, and the Actions by commits;
  an SBOM of the built image (its Debian packages, its C libraries) and of Pyodide's WebAssembly is still to be
  generated, where the image is built.
* **What the assessment did not cover**: an authenticated test of the business logic, isolation between research
  sessions, uploads, concurrency and load — in a separate environment, with test identities.

## Consequences

* A deploy installs exactly what is committed; a new wrangler, Action or base image arrives as a pull request, audited
  and tested before it is merged.
* Changing a dependency in `pyproject.toml` means running `requirements/lock.sh` (CI's install fails otherwise);
  a weekly audit run can turn red on a new advisory with nothing changed here.
* A change to a page's inline script needs its hash in both `CSP` and `CSP_REPORT_ONLY` (the test says which).
* Rollback, each one line in `wrangler.toml` merged to main: `CSP = ""` returns the page to reporting only;
  `SENTINEL = "observe"` stops refusals while keeping the records.
