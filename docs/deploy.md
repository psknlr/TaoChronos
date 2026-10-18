# 道乃久 on Cloudflare Workers Paid — the deployment guidebook

For the owner of the Cloudflare account and of this repository.  It says where the deployment stands, what stands
between it and the full corpus, and every step from there: the full corpus (958 books) by GitHub Actions or from your own
computer, rebuilding the corpus from its sources, the default service, the archive, the edge rules, and running it all.
It assumes the account is on **Workers Paid**, which also puts D1, Durable Objects and Containers on paid, usage-based
terms.

简体中文（新加坡）版本：[deploy.zh-SG.md](deploy.zh-SG.md).  The older guides it gathers up: [cloud/SETUP.md](../cloud/SETUP.md),
[cloud/README.md](../cloud/README.md), [relay/SETUP.md](../relay/SETUP.md), [security/README.md](../security/README.md).  The
decisions behind it: ADRs [0012](adr/0012-default-service-relay.md), [0016](adr/0016-site-and-full-corpus-on-cloudflare.md),
[0017](adr/0017-d1-backup.md), [0018](adr/0018-sentinel-and-edge-rules.md), [0023](adr/0023-workers-paid.md).

Times are in UTC and Singapore time (SGT, UTC+8).  Cloudflare's and GitHub's labels are quoted as they appear on screen.

**The short way to the full corpus:** read Part 1 (five minutes), do Part 2 (unblock), then *either* Route A *or* Route B
of Part 3.  Part 4 is the rest; Part 5 is for afterwards.

---

## Contents

- [Part 1. Where things stand](#part-1-where-things-stand)
- [Part 2. Unblock: GitHub Actions and the deploy token](#part-2-unblock-github-actions-and-the-deploy-token)
- [Part 3. The whole corpus](#part-3-the-whole-corpus)
- [Part 4. The other steps](#part-4-the-other-steps)
- [Part 5. Running it](#part-5-running-it)

---

## Part 1. Where things stand

Read from the repository's workflow logs on 17 October 2026.

| Part | State | How we know |
|---|---|---|
| Site `chat.impf.ai` | **Live**, deployed 11 Oct 17:31 UTC (version `4c6d9a24…`), serving only the 要籍语料 in the browser | site run of 11 Oct: `the site runs without the full corpus` |
| Default service `chat-api.impf.ai` | **Live**, deployed 11 Oct 17:30 UTC | relay run of 11 Oct |
| Full-corpus store (958 books) | **Uploaded** to the KV namespace `taochronos-store`: all 6 parts present and their checksums verified | canon run of 11 Oct 00:38 UTC fetched and checked every part; `cloud/store.json` unchanged since 1 Oct |
| Full corpus: container | **Never deployed** | site runs: Containers API answered `401` — the token lacked **Containers · Edit** (or the account was still on Free) |
| Full corpus: D1 backup | **Never imported** | every d1 run that started (1–11 Oct) stopped within 20 s at the token check; the last: `the API token may not use D1 (HTTP 401)` — the token lacked **D1 · Edit** |
| The Workers Paid changes (ADR 0023, PR #35) | **Merged to `main`, not deployed** | the deploys of 14 Oct never started (below) |
| GitHub Actions | **Starts no job since 11 Oct ~20:20 UTC** | every run since fails in ~4 s with no runner and no log |

What this means:

1. **The corpus does not need to be rebuilt.**  The store the site needs is already in Cloudflare.  What is missing is
   turning it into a service: building the container from it, and importing it into D1.
2. **Two permissions on the deploy token** — Containers · Edit and D1 · Edit — stopped both until now.
3. **GitHub Actions** stops everything that runs through it: deploys, the hourly collection of conversation records
   (they wait safely in the relay meanwhile), the daily D1 and security runs.  Fix it (Part 2.1), or deploy from your
   own computer (Part 3, Route B), or both.

---

## Part 2. Unblock: GitHub Actions and the deploy token

### 2.1 GitHub Actions

**Find the reason.**  Open any recent failed run, e.g. **Actions → relay →** the run *Merge pull request #35*.  GitHub
writes why a job did not start at the top of the run page (the API does not show it).  For a private repository it is
usually one of:

| Message (in substance) | Cause | Fix |
|---|---|---|
| *recent account payments have failed or your spending limit needs to be increased* | the month's included Actions minutes are used up, and the budget / spending limit for Actions is 0 or reached | GitHub → your avatar → **Settings → Billing and licensing**: under *Usage* see the Actions minutes; under *Budgets* (or *Spending limits*) raise the Actions budget, or lift the stop at the limit; make sure a payment method is valid |
| *your account is locked due to a billing issue* | a failed payment | **Billing and licensing → Payment information**: update the card; then re-run |
| *Actions is disabled for this repository* | a setting | repository **Settings → Actions → General → Actions permissions** |

After the fix, re-run the two deploys of the merge: **Actions → relay →** *Merge pull request #35* **→ Re-run all jobs**,
then the same for **site**.  (Do Part 2.2 first, so that the site's run builds the container too.)

**Why the minutes ran out, and how to spend fewer.**  A private repository on GitHub Free has 2,000 Linux minutes a
month (Pro: 3,000); every job is rounded up to a whole minute.

| Workflow | Roughly | Saving |
|---|---|---|
| `ci` on every push of every branch: 4 jobs | 10–15 min a push; about 180 runs so far | the largest share. Push less often, or limit `ci.yml` to pull requests and `main` |
| `chat-logs` hourly | ~720 min a month even when there is nothing to collect | once the archive is on for both Workers (Part 4.2), **Actions → chat-logs → ⋯ → Disable workflow** |
| `d1` import | up to 300 min a run | import from your own computer (Route B, step B5) |
| `site` with a container build | 20–30 min | only when the corpus or its code changes |
| `security`, `pages`, `relay`, `site` without a build | 1–3 min each | — |

### 2.2 The Cloudflare deploy token

The secret `CLOUDFLARE_API_TOKEN` is the deploy token.  It needs exactly these permissions
(**My Profile → API Tokens →** the token **→ ⋯ → Edit**; editing permissions keeps its value):

| Scope | Permission | Level | For |
|---|---|---|---|
| Account | Workers Scripts | Edit | both Workers and their Durable Objects |
| Account | Account Settings | Read | wrangler |
| Account | Workers KV Storage | Edit | the store's namespace |
| Account | **Containers** | **Edit** | the full corpus's container — **missing until now** |
| Account | **D1** | **Edit** | the D1 backup — **missing until now** |
| Account | **Workers R2 Storage** | **Edit** | the archive (Part 4.2) |
| Zone | Workers Routes | Edit | the custom domains |

- **Account Resources**: *Include* → your account.  **Zone Resources**: *Include* → *Specific zone* → `impf.ai`.
- **Client IP Address Filtering**: empty.  **TTL**: empty, or a date you will remember to renew before.

**Check it from any computer** (the token's value is not readable from GitHub; if you no longer have it, create a new
token with the table above, store it as the secret `CLOUDFLARE_API_TOKEN`, and use it here):

```bash
export CLOUDFLARE_API_TOKEN=…            # the deploy token
export CLOUDFLARE_ACCOUNT_ID=…           # Dashboard → any zone → Overview → API → Account ID
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
for p in containers/me "d1/database?per_page=1" "storage/kv/namespaces?per_page=100" "r2/buckets"; do
  printf '%-36s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$api/$p"
done
```

Every line should read `200`.  `401` or `403` on `containers/me`: no Containers · Edit, or the plan is not Workers Paid;
on `d1/database`: no D1 · Edit; on `r2/buckets`: no R2 permission (needed only for the archive).  These are the same
checks the workflows make.

### 2.3 GitHub secrets and variables

Repository → **Settings → Secrets and variables → Actions**.  Secrets in the **Secrets** tab (*Repository secrets*),
variables in the **Variables** tab.

| Secret | Value | Needed |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | the deploy token (2.2) | yes |
| `CLOUDFLARE_ACCOUNT_ID` | the Account ID | yes |
| `MINIMAX_API_KEY` | the MiniMax key | yes, for the default service |
| `LOG_EXPORT_TOKEN` | 16+ random characters: `openssl rand -hex 32` | yes |
| `SENTINEL_SALT` | `openssl rand -hex 32` | recommended |
| `STATS_TOKEN` | 16+ random characters | optional (**设置 → 统计**) |
| `CLOUDFLARE_SECURITY_TOKEN` | Zone WAF, Zone Settings, Bot Management: Edit; Zone: Read; Account Filter Lists: Edit (zone `impf.ai`) | for the edge rules |
| `CLOUDFLARE_ANALYTICS_TOKEN` | Zone Analytics: Read (zone `impf.ai`) | for the edge's daily events |

| Variable | Value | When |
|---|---|---|
| `CLOUDFLARE_ZONE_ID` | `impf.ai` → **Overview** → *API* → Zone ID | for the edge's daily events |
| `ARCHIVE_BUCKET` | e.g. `taochronos-archive` | the archive (Part 4.2) |
| `STORE_TOKEN_SHA256` | sha256 of a one-off upload token | only while uploading a new corpus (3.4); delete it after |
| `D1_BUDGET` | `90000` | only on the D1 Free plan (a slice a day); unset on Paid |
| `RELAY_URL`, `SITE_URL` | other addresses | only if not `chat-api.impf.ai` / `chat.impf.ai` |

---

## Part 3. The whole corpus

### 3.1 What it is, and how it reaches a visitor

The full corpus is every work the project holds whose terms allow it to be published with the site: **958 books,
2,038,497 passages, 122,219,380 characters** (`cloud/store.json`, sha256 `ef628936…`; sources and terms in
[cloud/ATTRIBUTION.md](../cloud/ATTRIBUTION.md)).  It travels as one compressed SQLite file of 143 MB in six parts of
24 MiB, kept in the site's KV namespace.  Two services are built from it:

| | Container (`taochronos-corpus`) | D1 backup (`taochronos-d1-0 … -4`) |
|---|---|---|
| What runs | taochronos itself (Python) on the store, indexed, caches warmed | the site's Worker, on the store laid out in five D1 databases |
| Tools | all, research runs included | 14 computed live, 16 precomputed for common entries, the rest (research, 句读, D1–D5 …) unavailable |
| Built by | the `site` workflow (job *corpus*), or `wrangler deploy` (Route B) | the `d1` workflow, or `python -m taochronos.chat.d1 import` (Route B) |
| Takes | ~20 min to build; tens of seconds to wake after sleeping | ~2 h to import, once |
| Costs | while running (sleeps after 15 idle minutes) | storage ~1.5 GB, reads per search |

The site sends the API to the container when one is deployed; otherwise to the D1 backup when its import is complete;
otherwise the page runs the 要籍语料 (535 works) in the browser.  **Deploy both**: the container is the full service, and
D1 serves whenever a deployment finds no container (a failed build, say), so readers never drop back to the browser's
smaller corpus for that reason.

### 3.2 Route A — with GitHub Actions

Needs: Part 2.1 fixed, Part 2.2 done.

**A1. The container.**
1. **Actions → site → Run workflow** → branch `main` → tick **rebuild** → **Run workflow**.
2. Job **corpus**:
   - *Which version … may the account deploy containers?* prints `deployed: none; this commit: ef628936d382-…` and no
     warning.  (`the account may not deploy containers yet` → back to 2.2.)
   - *The store, from the site's KV namespace* fetches the six parts and checks each.
   - *Build the image and deploy the corpus Worker*: ~20 minutes.
3. Job **bind** deploys the site again, bound to the container, and searches the full corpus; its log ends with
   `a search on the full corpus: …`.

**A2. The D1 backup.**
1. **Actions → d1 → Run workflow** → branch `main` → **budget** `1000000` (the default) → **Run workflow**.  (The budget
   was the Free plan's daily cap of 100,000 rows; on Paid it is only a safety valve.  The import writes about 100,000
   rows.  The daily run at 00:07 UTC uses the same default, so it imports everything too; so does a run started by a
   push to `main` that changes `cloud/store.json` or the importer, once a run already going has finished.)
2. It writes the corpus (~87,000 rows, about an hour and a half), then computes the precomputed results (~12,000 rows)
   in as many processes as the runner has processors: about half an hour on four, two hours on one (estimates).  Ending
   with `the run's time is up` (five hours) means it was cut short: run it again and it resumes, writing nothing twice;
   the daily run at 00:07 UTC (08:07 SGT) resumes it too.
3. When complete, the run's **Summary** says `complete: yes`, it records the version in KV and starts the **site**
   workflow itself, which binds the databases.

**A3. Check** as in 3.5.

### 3.3 Route B — from your own computer

Does what the workflows do, with the same commands, on a machine of yours.  Use it while GitHub Actions is blocked, or to
save its minutes (the D1 import alone takes about two hours of them).

**B0. The machine.**

| Needs | Why |
|---|---|
| **Linux x86-64**: Ubuntu 22.04 or 24.04, a cloud VM, or **WSL2** on Windows | `cloud/site/deploy.sh` uses GNU `sed`; Cloudflare's containers run `linux/amd64` images, which build slowly under emulation on an ARM Mac |
| **Docker** (Docker Engine, or Docker Desktop with WSL2) | wrangler builds the container image locally |
| Node.js 22, Python 3.12, git, curl, xz-utils | the Workers, taochronos, the downloads |
| ~30 GB free disk, a steady upload | the store unpacked and indexed, the image (1.8 GB) and its layers; the image is uploaded to Cloudflare |
| The deploy token and the Account ID | Part 2.2 |

Long steps (B3, B5) survive a closed laptop lid only in `tmux` or `screen`; start them there.

**B1. Set up.**

```bash
git clone https://github.com/psknlr/TaoChronos.git && cd TaoChronos     # main, with PR #35
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
export CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=…
export WRANGLER=wrangler@4.142.0 WRANGLER_SEND_METRICS=false
export STORE_NAMESPACE=taochronos-store SITE_URL=https://chat.impf.ai RELAY_URL=https://chat-api.impf.ai
export ARCHIVE_BUCKET=                                                  # the bucket's name once the archive is set up (4.2)
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
auth="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
NS=$(curl -fsS -H "$auth" "$api/storage/kv/namespaces?per_page=100" \
  | python3 -c 'import json,sys,os; print(next(n["id"] for n in json.load(sys.stdin)["result"] if n["title"]==os.environ["STORE_NAMESPACE"]))')
echo "KV namespace: $NS"
```

**B2. Fetch the store from KV and check it** (the workflows' own commands):

```bash
mkdir -p cloud/.store/parts
python3 - <<'EOF' > cloud/.store/parts.txt
import json, urllib.parse
m = json.load(open("cloud/store.json"))
for p in m["parts"]:
    print(urllib.parse.quote(m["key"] + p["name"], safe=""), p["name"], p["sha256"])
EOF
while read -r key name sha; do
  curl -fsS -H "$auth" "$api/storage/kv/namespaces/$NS/values/$key" -o "cloud/.store/parts/$name"
  echo "$sha  cloud/.store/parts/$name" | sha256sum -c --quiet
done < cloud/.store/parts.txt
sha=$(python3 -c 'import json; print(json.load(open("cloud/store.json"))["sha256"])')
while read -r _ name _; do cat "cloud/.store/parts/$name"; done < cloud/.store/parts.txt > "cloud/.store/$sha.sqlite.xz"
echo "$sha  cloud/.store/$sha.sqlite.xz" | sha256sum -c && rm -rf cloud/.store/parts cloud/.store/parts.txt
```

The last check prints `… OK`.  A `curl: (22) … 404` means a part is not in KV: upload the store (3.4) first.

**B3. Build and deploy the container.**

```bash
# the version the workflow would give this commit: the store and every file the image is built from
store=$(python3 -c 'import json; print(json.load(open("cloud/store.json"))["sha256"])')
tree=$(git ls-tree -r HEAD -- pyproject.toml README.md src architecture-policy.yaml profiles domains corpus/catalog corpus/demo \
         corpus/modern agents skills evals/gold cloud/corpus cloud/store.json .dockerignore | sha256sum | cut -c1-12)
VERSION="${store:0:12}-${tree}"; echo "$VERSION"
(cd cloud/corpus && npm ci --no-audit --no-fund && npx --yes "$WRANGLER" deploy --var "VERSION:$VERSION")
# recorded as deployed, as the workflow does — only after the deploy succeeded
curl -fsS -X PUT -H "$auth" -H "Content-Type: text/plain" --data-binary "$VERSION" "$api/storage/kv/namespaces/$NS/values/deployed%2Fcorpus" >/dev/null && echo recorded
```

The image build unpacks and indexes the store and warms the tools' caches (10–25 minutes, depending on the machine),
then uploads 1.8 GB.  wrangler ends with `Deployed taochronos-corpus`.

**B4. Deploy the site, bound to it.**

```bash
taochronos web build -o _site --relay "$RELAY_URL" --unlist minimax,minimax-global
CORPUS_DEPLOYED=1 bash cloud/site/deploy.sh
```

`deploy.sh` binds what the account has (the store's namespace, the container, the D1 databases once imported, the
archive when `ARCHIVE_BUCKET` names a private bucket), deploys, and checks the site.  The Worker keeps the secrets it
already has: no need to supply `LOG_EXPORT_TOKEN` and the others here (the warning that it is not set only means it is
not rewritten).  The log ends with `a search on the full corpus: …`.  The first call after a new image may take minutes
while the container starts; `deploy.sh` waits for it.

**B5. Import the D1 backup** (about two hours with four processors; in `tmux`):

```bash
xz="cloud/.store/$sha.sqlite.xz"
PYTHONHASHSEED=0 python -m taochronos.chat.d1 import "$xz" --manifest cloud/store.json --work cloud/.d1 \
  --api --budget 1000000 --reset --precompute --workers 0 --report cloud/.d1/report.json
python3 -c 'import json; r=json.load(open("cloud/.d1/report.json")); print(r["version"], "complete" if r["complete"] else r["stopped"])'
```

Interrupted (network, laptop)?  Run the same command again: it reads from the databases where it got to and writes nothing
twice.  When the last line says `complete`:

```bash
D1V=$(python -m taochronos.chat.d1 version)
curl -fsS -X PUT -H "$auth" -H "Content-Type: text/plain" --data-binary "$D1V" "$api/storage/kv/namespaces/$NS/values/deployed%2Fd1" >/dev/null && echo recorded
CORPUS_DEPLOYED=1 bash cloud/site/deploy.sh            # the site again, now bound to the five databases as well
```

**B6. Check** as in 3.5.  **B7.** The default service from your computer: Part 4.1.

When done, `cloud/.store/`, `cloud/.d1/` and `_site/` can be deleted; git ignores them.

### 3.4 Updating the corpus: rebuilding the store from its sources

Only when the corpus itself changes (new sources, new texts, a new normaliser).  The store in KV serves until then.

**What goes in.**  The site's store takes only the sources whose terms allow publishing (`WEB_SOURCES`), never those
that forbid it (`NEVER_PACKED`):

| Source | Command name | In the site's store | Licence |
|---|---|---|---|
| Kanseki Repository KR3e (四库全书 医家类, 100 works) and its catalogue | `kanripo`, `kr-catalog` | yes | CC BY-SA 4.0 |
| 中醫笈成 v1.4.8 (816 works) | `jicheng` (**archive supplied by you**: `jc_1_4_8_all.7z.001 … .003`) | yes | CC0 1.0 (the editing) |
| McGill rare gynaecology books | `mcgill` | yes | Public Domain Mark |
| 數位中醫校書郎 CMETA (11 collated editions) | `cmeta` | yes | CC BY 4.0 |
| 维基文库 Wikisource (dumps) | `wikisource` | yes | CC BY-SA 4.0 |
| TCM-Ancient-Books, tcmoc | `tcm-ancient-books`, `tcmoc` | yes, by the publisher's decision; copies of 笈成 texts left out | none stated |
| 東亜医学協会 | `aeam` | **never** | no redistribution |
| Hugging Face classical-tcm-canon | `hf-tcm-canon` | **never** | proprietary |

**Build the full local corpus** (a machine with the disk and time for it; the texts go to `.taochronos/`, which git ignores):

```bash
pip install -e ".[pdf,parquet]"          # pypdf reads the aeam PDFs, pyarrow the Hugging Face Parquet file
taochronos corpus fetch kanripo && taochronos corpus ingest kanripo
taochronos corpus fetch kr-catalog && taochronos corpus catalog kr-catalog && taochronos corpus ingest kanripo --changed
taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 jc_1_4_8_all.7z.003
taochronos corpus catalog jicheng && taochronos corpus ingest jicheng
for s in mcgill cmeta aeam wikisource tcm-ancient-books tcmoc hf-tcm-canon; do
  taochronos corpus fetch $s && taochronos corpus catalog $s && taochronos corpus ingest $s
done
taochronos corpus status                 # books, passages, periods; whether the index matches the variant table
taochronos corpus reindex                # only if status says it does not (the 笈成 catalogue adds variants)
```

`aeam` and `hf-tcm-canon` are taken **locally only** — `web store` never puts them in the site's store — because the
lower-ranked sources (Wikisource, the web text sets) are deduplicated against them: without them, copies of their texts
would be admitted, and the store would differ from the one published.  Each fetch is pinned in
`corpus/sources.lock.yaml`; with the same sources the same texts come back.  Details per source: [docs/data.md](data.md).

**Write and upload the site's store:**

```bash
t=$(openssl rand -hex 32); printf %s "$t" | sha256sum       # a one-off upload token and its sha256 (the token stays on this machine)
# GitHub → Settings → Secrets and variables → Actions → Variables: STORE_TOKEN_SHA256 = that sha256, then
# Actions → site → Run workflow — or, on the Route B machine: STORE_TOKEN_SHA256=<that sha256> bash cloud/site/deploy.sh
taochronos web store                                         # .taochronos/cloud/<sha256>.sqlite.xz, cloud/store.json, cloud/ATTRIBUTION.md
TAOCHRONOS_STORE_TOKEN=$t taochronos web upload              # six parts to https://chat.impf.ai/api/store/… (parts already there are skipped)
# delete the variable STORE_TOKEN_SHA256 at once, and deploy the site again so that uploads are off
git add cloud/store.json cloud/ATTRIBUTION.md && git commit -m "The site's store: …"   # then a pull request to main
```

A new `cloud/store.json` is a new version: once it is on `main`, Route A (A1 and A2) or Route B (B2–B5) builds the new
container and re-imports D1 (the old databases are replaced; meanwhile the container, or the page's browser corpus,
answers).

*Without a local corpus:* the **canon** workflow (Actions → canon → Run workflow) re-ranks the 要籍 and repacks the
browser's 要籍语料 from the store already in KV; it does not change the full corpus itself.

### 3.5 Checking the full corpus

```bash
curl -s https://chat.impf.ai/api/info | python3 -c 'import json,sys; i=json.load(sys.stdin); c=i.get("corpus",{}); print(i.get("runtime"), c.get("label"), c.get("books"), "backup" if i.get("backup") else "")'
#   container:   … 全量语料 958
#   D1 backup:   d1 全量语料（备份） 958 backup       (only when no container is bound)
#   neither:     an error with "corpus": "none" — the page runs the 要籍语料 in the browser
curl -s -X POST -H "Content-Type: application/json" -H "Origin: https://chat.impf.ai" \
  -d '{"name":"classics.search","arguments":{"query":"桂枝汤","k":3}}' https://chat.impf.ai/api/call | head -c 400; echo
```

In the dashboard: **Workers & Pages** lists `taochronos-corpus`; **Storage & databases → D1** lists `taochronos-d1-0` … `-4`.
In the page: ask 「桂枝汤的组成出自哪部书？」 and open a citation; **设置 → 关于** links to the full corpus's sources.

The container sleeps after 15 idle minutes (`SLEEP_AFTER`); the first visitor afterwards wakes it, usually within the
time they take to type a question.

---

## Part 4. The other steps

### 4.1 The default service (relay)

**By GitHub Actions:** re-run **relay** (Part 2.1).  **From your computer** (after B1):

```bash
cd relay && cp wrangler.toml wrangler.deploy.toml && bash ../security/bind-archive.sh wrangler.deploy.toml
npx --yes "$WRANGLER" deploy --config wrangler.deploy.toml && cd ..
python3 relay/collect.py check                              # one tiny model call through the relay: ends with "call": "ok"
```

The Worker keeps its secrets (`MINIMAX_API_KEY`, `LOG_EXPORT_TOKEN`, …) across deploys.  To change one:
`printf %s "$VALUE" | npx --yes "$WRANGLER" secret put NAME --config relay/wrangler.deploy.toml`, and update the GitHub
secret of the same name.

**MiniMax key from the international platform** (platform.minimax.io — the usual case outside mainland China):
`relay/wrangler.toml` must say `UPSTREAM_BASE = "https://api.minimax.io/v1"`; the check says
`MiniMax refused the key … api.minimax.io` otherwise.

**Collecting records while Actions is blocked** (optional — they wait safely in the relay, up to 50,000):

```bash
export LOG_EXPORT_TOKEN=…                                   # if lost: a new one in GitHub and on both Workers (secret put)
out=$(python3 relay/collect.py pull --out data/chat-logs) && echo "$out"
LAST=$(printf '%s\n' "$out" | tail -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["last"])')
# the relay deletes what it gave only once the repository holds it: the ack runs only if the push succeeded
git add data/chat-logs && git commit -m "chat-logs: through #$LAST" && git push && python3 relay/collect.py ack --through "$LAST"
```

### 4.2 The archive: records out of the repository

The hourly `chat-logs` workflow commits visitors' consented conversations, and the sentinels' events, into this
repository, whose history cannot be cleaned without rewriting it.  With the archive, both Workers keep them in a private
R2 bucket instead.

1. **R2 Object Storage → Create bucket** → `taochronos-archive` → location *Automatic* (or *Asia-Pacific*).  In its
   **Settings**: **Public Development URL (r2.dev)** stays **Disabled**; no **Custom Domains**.
2. The deploy token has **Workers R2 Storage · Edit** (2.2).
3. Repository variable `ARCHIVE_BUCKET` = `taochronos-archive` (and, for Route B, `export ARCHIVE_BUCKET=taochronos-archive`).
4. Deploy both Workers: re-run **relay** and **site**, or 4.1 and B4.  Each deploy log shows
   `the archive: R2 bucket taochronos-archive (private): …`; a `::warning::` or `::error::` there says why it was not
   bound (not found, no permission, possibly public), and records keep going to the repository — nothing is lost.
5. About half a minute after the next consented conversation the bucket holds `chat-logs/YYYY/MM/DD/<id>.json`.  Then
   **Actions → chat-logs → ⋯ → Disable workflow** saves ~720 Actions minutes a month.
6. Reading a day back (`.archive/` is ignored by git — never commit it):

   ```bash
   export LOG_EXPORT_TOKEN=…
   python3 relay/collect.py archive --day 2026-10-17           # → .archive/chat-logs/2026/10/17.jsonl
   python3 security/collect.py archive --day 2026-10-17        # → .archive/security-logs/{relay,site}/2026/10/17.jsonl
   ```

7. Retention — the publisher's decision, to be stated in the page's notice; suggested 90 days for conversations, 30 for
   events:

   ```bash
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive chat-logs-90d chat-logs/ --expire-days 90
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive security-30d security-logs/ --expire-days 30
   ```

To stop: delete `ARCHIVE_BUCKET`, deploy both Workers, enable `chat-logs` again; the collectors resume from their cursors.

### 4.3 The edge rules

1. Secrets `CLOUDFLARE_SECURITY_TOKEN`, `CLOUDFLARE_ANALYTICS_TOKEN`, variable `CLOUDFLARE_ZONE_ID` (2.3).
2. **Actions → security → Run workflow**, action `plan` (writes nothing), then again with `apply`.
   From your computer: `pip install pyyaml && CLOUDFLARE_SECURITY_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… python3 security/apply.py plan`
   (then `apply`).
3. After 48 hours: **impf.ai → Security → Events**, filter `[taochronos]`: no genuine visitor blocked.

The rules fit the zone's own plan (Free: 5 custom rules, one 10-second rate limit); Workers Paid does not change them.

### 4.4 Tuning for Paid

| What | Where | Recommendation |
|---|---|---|
| Sentinel | `SENTINEL` in `relay/wrangler.toml`, `cloud/site/wrangler.toml` | after two weeks of `observe` with no genuine visitor among the `shadow` events, `"enforce"` in both |
| Model spend per address | `TOKENS_PER_DAY`, `PER_DAY` (relay) | 10 M tokens, 600 calls a day; many people behind one hospital or office address share them — raise if they run out |
| Model spend in all | `TOTAL_TOKENS_PER_DAY`, `TOTAL_PER_DAY` (relay) | the ceiling on a bad day: set it from your MiniMax budget |
| Site's daily caps | `API_READS_PER_DAY`, `API_CALLS_PER_DAY` (site) | 6,000 / 3,000 per address, wide on purpose |
| Records waiting | `LOG_KEEP` (relay) | 50,000; beyond, new records are refused (`logs full` logged), none dropped |
| Container | `SLEEP_AFTER`, `instance_type`, `LOCATION_HINT` (`cloud/corpus/wrangler.toml`) | `15m`, `standard-1`, `apac` (right for Singapore and East Asia; fixed when first created) |

Change on `main` (a pull request), then deploy (Actions, or Route B).

### 4.5 The whole order, as a checklist

1. ☐ Part 1 read; the reason Actions stopped found (2.1)
2. ☐ Deploy token: Containers, D1, R2 permissions; the four checks print `200` (2.2)
3. ☐ Actions running again — *or* a Linux machine ready for Route B (B0, B1)
4. ☐ Relay deployed with PR #35 (4.1); `collect.py check` → `"call": "ok"`
5. ☐ Container deployed and the site bound to it (A1, or B2–B4); `/api/info` → `全量语料 958`
6. ☐ D1 imported and bound (A2, or B5)
7. ☐ Archive bucket and `ARCHIVE_BUCKET`; both Workers deployed; `chat-logs` disabled (4.2)
8. ☐ Edge rules applied (4.3)
9. ☐ After two weeks: sentinel to `enforce` (4.4)

---

## Part 5. Running it

### 5.1 Checking everything

```bash
curl -sI https://chat.impf.ai/ | grep -iE '^(HTTP|server|strict-transport-security)'      # 200, cloudflare, max-age=…
curl -s -o /dev/null -w '%{http_code}\n' http://chat.impf.ai/                              # 301
curl -s https://chat-api.impf.ai/v1/health                                                 # "ok":true
python3 relay/collect.py check                                                             # "call": "ok"
LOG_EXPORT_TOKEN=… python3 security/collect.py summary                                     # what the sentinels see now
```

Plus 3.5 for the corpus.

### 5.2 What runs on its own

| Workflow | When (UTC / SGT) | Does |
|---|---|---|
| `relay` | a push to `main` touching `relay/` or `security/` | test, deploy, check the relay |
| `site` | a push to `main` touching the site, code, corpus or `security/` | deploy the site; build the container when its inputs changed; bind and check |
| `chat-logs` | hourly at :17 | records and events into the repository (only from a Worker without the archive) |
| `d1` | daily 00:07 UTC / 08:07 SGT | resume or check the D1 import |
| `security` | daily 01:41 UTC / 09:41 SGT; a push of `security/blocklist.yaml` | the edge's events; the block list |
| `pages` | a push touching the web client | the GitHub Pages mirror |
| `ci` | every push and pull request | tests |

Inside the Workers: the archive's alarms; the container's sleep.

### 5.3 Costs

Cloudflare bills in US dollars: Workers Paid 5 USD a month plus use beyond each allowance.  Figures as published at the
time of writing — confirm on the pricing pages ([Workers](https://developers.cloudflare.com/workers/platform/pricing/),
[Containers](https://developers.cloudflare.com/containers/pricing/), [D1](https://developers.cloudflare.com/d1/platform/pricing/),
[Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/), [R2](https://developers.cloudflare.com/r2/pricing/)).

| Item | Included a month | This site |
|---|---|---|
| Workers | 10 M requests, 30 M CPU-ms | only pages and `/api/*` pass through a Worker |
| Containers | 25 GiB-h memory, 375 vCPU-min, 200 GB-h disk | `standard-1` ~0.036 USD per running hour: ~4 USD/month at 4 h a day, ~30 USD never sleeping |
| D1 | 25 bn rows read, 50 M written, 5 GB | ~1.5 GB; one import ~100 k rows |
| Durable Objects | 1 M requests, plus duration and storage | a few per call |
| Workers KV | 1 GB | the store, 143 MB |
| R2 | 10 GB-month, 1 M Class A, 10 M Class B | one write per record or event |
| **MiniMax** | your balance | by far the largest; bounded by the relay's limits (4.4) |
| **GitHub Actions** | 2,000 min (Free) / 3,000 (Pro) for a private repository | see 2.1 |

Billing alerts are not caps: set one anyway (Cloudflare **Notifications → Add → Billing**, where offered; GitHub
**Budgets**), and keep the MiniMax balance at what you are willing to spend.

### 5.4 Day-to-day

| Task | How |
|---|---|
| Rotate the MiniMax key | new key → secret `MINIMAX_API_KEY` → deploy the relay (Actions, or `secret put` in 4.1) → delete the old key |
| Rotate the deploy token | new token (2.2) → secret `CLOUDFLARE_API_TOKEN` → delete the old one |
| Rotate the collector token | new value → secret `LOG_EXPORT_TOKEN` → `secret put` on both Workers (or deploy both by Actions) |
| Update the corpus | 3.4, then A1+A2 or B2–B5 |
| Change limits or modes | `[vars]` in the Worker's `wrangler.toml`, through a pull request |
| Stop recording conversations | `LOGS = "off"` in `relay/wrangler.toml` |
| Pause the default service | Dashboard → `taochronos-relay` → **Settings → Variables and Secrets** → delete `MINIMAX_API_KEY` |
| Block an address now | **Manage Account → Configurations → Lists → `taochronos_block`**, then `security/blocklist.yaml` |

### 5.5 Rolling back

- **A Worker:** Dashboard → **Workers & Pages** → the Worker → **Deployments** → an earlier version → **Rollback**; or
  revert the commit on `main` and deploy.  PR #35 adds no Durable Object migration, so rolling back over it is safe.
- **The container:** deploy it from an earlier commit (A1 on that ref, or B3 in a checkout of it).
- **The D1 backup:** nothing to roll back; without its `deployed/d1` record the site does not use it.
- **Back to GitHub Pages** (last resort): remove `chat.impf.ai` from the site Worker's **Domains & Routes**; CNAME
  `chat` → `psknlr.github.io`, **DNS only**; the custom domain under the repository's **Settings → Pages**.

### 5.6 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| every run fails in seconds, no log | GitHub Actions not starting jobs | 2.1 |
| `the account may not deploy containers yet` | no Containers · Edit, or not Workers Paid | 2.2 |
| `the API token may not use D1 (HTTP 401)` | no D1 · Edit | 2.2 |
| `the store … is not (all) in the KV namespace` / B2 `curl: (22) … 404` | the store not uploaded (or a new `store.json` not yet uploaded) | 3.4 |
| `container was not deployed` | the build or deploy failed (error just above) | fix, then A1 with **rebuild**, or B3 |
| B3: `Cannot connect to the Docker daemon` | Docker not running | start Docker (`sudo systemctl start docker`, or Docker Desktop) |
| B3: very slow build on a Mac | an amd64 image under emulation | use Linux x86-64 (B0) |
| B4: `sed: … extra characters` or `invalid command code` | macOS sed | run on Linux or WSL2 (B0) |
| B4/4.1: `Authentication error [code: 10000]` | token or Account ID wrong | 2.2's checks |
| `No access to the specified resource` (`workers/routes`) | the token's Zone Resources lack `impf.ai` | edit the token |
| `externally managed DNS records` | `chat` has a DNS record of the account's own | delete that one record in **impf.ai → DNS**, deploy again |
| d1 stops: `the day's budget` | the budget was reached (1,000,000 by default; less if `D1_BUDGET` is set) | run again with `1000000`, or delete `D1_BUDGET` |
| d1 stops: `the run's time is up` | five hours used | run again; it resumes |
| `/api/info` → 503, `corpus: none` | no container, no D1 bound | A1/A2 or B3–B5 |
| visitors see 「该地址因异常访问已被暂时限制」 | the sentinel refused the address (403) | read its events; if wrong, shorten `BLOCK_SECONDS` or `SENTINEL` back to `observe` |
| visitors see 「今天的查询次数已用完」 | the address's daily cap (429) | raise `API_READS_PER_DAY` / `API_CALLS_PER_DAY` if genuine |
| relay check: `MiniMax refused the key … api.minimax.io` | international key, mainland address (or the reverse) | `UPSTREAM_BASE` (4.1) |
| Workers Logs: `logs full` | records not collected for a long while | Actions back (2.1), 4.1's manual collection, or the archive (4.2) |
| `the archive's bucket … may be public` | r2.dev on, a custom domain, or the token cannot read them | 4.2 step 1, R2 permission |
| `chat-logs`: `the records could not be pushed` | `main` protected against Actions | allow Actions to push, or the archive |
| `chat-logs`: `HTTP 401` on export | `LOG_EXPORT_TOKEN` differs between GitHub and the Worker | set both to the same value |

### 5.7 Reference

| Path | What |
|---|---|
| `relay/wrangler.toml`, `relay/src/` | the default service |
| `cloud/site/wrangler.toml`, `cloud/site/src/`, `cloud/site/deploy.sh` | the site and its deployment |
| `cloud/corpus/wrangler.toml`, `cloud/corpus/Dockerfile` | the full corpus's container |
| `cloud/store.json`, `cloud/ATTRIBUTION.md` | the store deployed, its sources and terms |
| `src/taochronos/chat/d1.py`, `cloud/site/src/backup/` | the D1 backup: importer and Worker side |
| `security/sentinel.js`, `security/archive.js`, `security/bind-archive.sh` | the sentinel, the archive, the bucket check |
| `security/rules.yaml`, `security/blocklist.yaml`, `security/apply.py` | the edge |
| `relay/collect.py`, `security/collect.py` | the collectors (pull, ack, archive, summary, check) |
| `.github/workflows/` | `relay`, `site`, `d1`, `chat-logs`, `security`, `pages`, `canon`, `ci` |
