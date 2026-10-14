# Deploying 道乃久 on Cloudflare Workers Paid

A complete guide for the owner of the Cloudflare account and of this repository: what is deployed, which keys and
settings it needs, the steps in order, how to check each one, what runs on its own, what it costs, and what to do when
something goes wrong.  It assumes the account is on **Workers Paid** (which also brings D1, Durable Objects and
Containers onto paid, usage-based terms).

简体中文（新加坡）版本：[deploy.zh-SG.md](deploy.zh-SG.md).  The older step-by-step guides this one gathers up:
[cloud/SETUP.md](../cloud/SETUP.md) (the site), [relay/SETUP.md](../relay/SETUP.md) (the default service),
[security/README.md](../security/README.md) (the edge).  Design decisions: ADRs [0012](adr/0012-default-service-relay.md),
[0016](adr/0016-site-and-full-corpus-on-cloudflare.md), [0017](adr/0017-d1-backup.md), [0018](adr/0018-sentinel-and-edge-rules.md),
[0023](adr/0023-workers-paid.md).

Times are given in UTC and Singapore time (SGT, UTC+8).  Cloudflare's dashboard is in English; its labels are quoted as
they appear there.

---

## Contents

1. [What gets deployed](#1-what-gets-deployed)
2. [Before you start](#2-before-you-start)
3. [Cloudflare API tokens](#3-cloudflare-api-tokens)
4. [GitHub secrets and variables](#4-github-secrets-and-variables)
5. [Path A — upgrading the running Free deployment](#5-path-a--upgrading-the-running-free-deployment) (most likely yours)
6. [Path B — a new account from nothing](#6-path-b--a-new-account-from-nothing)
7. [Checking the deployment](#7-checking-the-deployment)
8. [What runs on its own](#8-what-runs-on-its-own)
9. [Costs and the guards on them](#9-costs-and-the-guards-on-them)
10. [Day-to-day operations](#10-day-to-day-operations)
11. [Rolling back](#11-rolling-back)
12. [Troubleshooting](#12-troubleshooting)
13. [Reference: files and workflows](#13-reference-files-and-workflows)

---

## 1. What gets deployed

```
Visitor's browser
  │
  ├── https://chat.impf.ai ──────────── Worker  taochronos-site        (cloud/site)
  │      │  pages, security headers, /api/*                 Durable Object Watch (the sentinel, the counts)
  │      │  static files are served by Cloudflare directly  KV namespace taochronos-store (the corpus upload)
  │      │
  │      ├── service binding ──▶ Worker taochronos-corpus   (cloud/corpus, no public address)
  │      │                         └─ Durable Object ▶ Container: taochronos on the full corpus (958 books)
  │      ├── or, without the container: D1 databases taochronos-d1-0 … -4 (the D1 backup)
  │      └── or, without either: the browser runs the 要籍语料 itself
  │
  └── https://chat-api.impf.ai ──────── Worker  taochronos-relay       (relay/)
         model calls with the owner's MiniMax key           Durable Objects Limiter (limits, sentinel, counts)
         consented conversation records                                 LogBook  (records waiting)
                                                            R2 bucket (optional): the archive

GitHub Actions ── deploys both Workers, builds the container image, imports D1, writes the edge rules,
                  collects records and security events (hourly), pulls the edge's events (daily)
```

| Part | Where | Needs | Without it |
|---|---|---|---|
| Default service (relay) | `chat-api.impf.ai` | MiniMax key | Visitors must enter their own model key |
| Site | `chat.impf.ai` | — | — |
| Full corpus, container | behind the site | Workers Paid, token with **Containers · Edit**, the store uploaded | The D1 backup answers, else the browser |
| Full corpus, D1 backup | behind the site | token with **D1 · Edit**, the store uploaded | The browser runs the 要籍语料 (535 works) |
| Archive | R2 bucket | token with **Workers R2 Storage · Edit**, `ARCHIVE_BUCKET` | Records and events are committed to the repository |
| Edge rules | zone `impf.ai` | two security tokens | Cloudflare's managed rules only |

**Which corpus answers.**  The site sends the API to the container whenever the container is deployed and bound.  The
D1 backup answers only when no container is bound, and the browser's 要籍语料 only when neither is.  On Workers Paid the
container is the full service (every tool, research runs included); the D1 backup is a low-cost standby that a
deployment falls back to if the container cannot be deployed.  Both are recommended.

---

## 2. Before you start

| You need | Notes |
|---|---|
| Cloudflare account on **Workers Paid** | Dashboard → **Compute (Workers)** → **Plans**.  Same account as the zone `impf.ai` |
| The zone `impf.ai` on that account | Its nameservers are `*.ns.cloudflare.com` |
| Admin rights on `psknlr/TaoChronos` | To open **Settings** and set secrets and variables |
| A MiniMax API key | Pay-as-you-go recommended (its balance is the hard ceiling on model spend).  From Singapore you will usually have an **international** key (platform.minimax.io): see step A1.3 |
| A machine with Python ≥ 3.11 and the full local corpus | Only if the full-corpus store has never been uploaded (step A3) |
| R2 enabled on the account | Only for the archive.  R2 asks for a payment method once; on Workers Paid it is already there |

---

## 3. Cloudflare API tokens

Three tokens, kept apart so that each can do only its own job.  Create them under **My Profile → API Tokens →
Create Token** (or **Manage Account → Account API Tokens**).

### 3.1 The deploy token — secret `CLOUDFLARE_API_TOKEN`

Start from the template **Edit Cloudflare Workers**, then make sure the permissions read exactly:

| Scope | Permission | Level | Used by |
|---|---|---|---|
| Account | Workers Scripts | Edit | both Workers and their Durable Objects |
| Account | Account Settings | Read | wrangler |
| Account | Workers KV Storage | Edit | the corpus upload namespace |
| Account | **Containers** | **Edit** | the full corpus's container |
| Account | **D1** | **Edit** | the D1 backup |
| Account | **Workers R2 Storage** | **Edit** | the archive (optional) |
| Zone | Workers Routes | Edit | the custom domains |

- **Account Resources**: *Include* → your account.  **Zone Resources**: *Include* → *Specific zone* → `impf.ai`
  (forgetting this is the most common cause of `No access to the specified resource`).
- **Client IP Address Filtering**: leave empty (GitHub's runners have no fixed address).
- If the token already exists (from the relay's setup), **Edit** it — not *Roll* — and add the missing rows.  Editing
  permissions does not change the token's value; nothing changes in GitHub.

### 3.2 The security token — secret `CLOUDFLARE_SECURITY_TOKEN`

Custom token, zone `impf.ai`: Zone · **Zone WAF** · Edit; Zone · **Zone Settings** · Edit; Zone · **Bot Management** ·
Edit; Zone · **Zone** · Read; Account · **Account Filter Lists** · Edit.

### 3.3 The analytics token — secret `CLOUDFLARE_ANALYTICS_TOKEN`

Custom token, zone `impf.ai`: Zone · **Analytics** · Read.

---

## 4. GitHub secrets and variables

Repository → **Settings → Secrets and variables → Actions**.  Secrets go under the **Secrets** tab as *Repository
secrets* (not *Environment secrets*); variables under the **Variables** tab.  Spaces and line breaks pasted with a value
are removed by the workflows.

### Secrets

| Name | Value | Required |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | the deploy token (3.1) | yes |
| `CLOUDFLARE_ACCOUNT_ID` | Dashboard → any zone → **Overview** → *API* → Account ID | yes |
| `MINIMAX_API_KEY` | the MiniMax key | yes, for the default service |
| `LOG_EXPORT_TOKEN` | a random string of 16+ characters: `openssl rand -hex 32` | yes |
| `SENTINEL_SALT` | a random string: `openssl rand -hex 32` | recommended (a visitor's hashed key stays the same across months) |
| `STATS_TOKEN` | a random string of 16+ characters | optional (the page's **设置 → 统计** pane) |
| `CLOUDFLARE_SECURITY_TOKEN` | the security token (3.2) | for the edge rules |
| `CLOUDFLARE_ANALYTICS_TOKEN` | the analytics token (3.3) | for the edge's daily events |

### Variables

| Name | Value | When |
|---|---|---|
| `CLOUDFLARE_ZONE_ID` | `impf.ai` → **Overview** → *API* → Zone ID | for the edge's daily events |
| `ARCHIVE_BUCKET` | the R2 bucket's name, e.g. `taochronos-archive` | to archive records in R2 (step A6) |
| `STORE_TOKEN_SHA256` | sha256 of a one-off upload token | **only while uploading the corpus** (step A3); delete it afterwards |
| `RELAY_URL`, `SITE_URL` | other addresses | only if not `chat-api.impf.ai` / `chat.impf.ai` |

Never paste a secret's value into an issue, a pull request, a chat or a commit.

---

## 5. Path A — upgrading the running Free deployment

The relay and the site are already running on the Free plan (the repository's hourly `chat-logs` commits show it).
Do the steps in order; each says how to tell that it worked.

### A1. Merge the Workers Paid changes, check the relay

1. Open a pull request from the branch `claude/vibrant-pascal-n9a7o2` (the changes of [ADR 0023](adr/0023-workers-paid.md))
   into `main` and merge it.  The merge starts the **relay** and **site** workflows by itself.
2. **Actions → relay** → the run → **deploy**: every step green; the last prints
   `{"relay": "https://chat-api.impf.ai", "model": "Tao-R1", …, "call": "ok"}`.
3. *If your MiniMax key is from the international platform* (platform.minimax.io — the usual case outside mainland
   China): `relay/wrangler.toml` must say `UPSTREAM_BASE = "https://api.minimax.io/v1"`.  If the check step reports
   `MiniMax refused the key … api.minimax.io`, edit that line on `main` and the relay deploys again.

What changes for visitors: a refused visitor is now told so (403 / 429, not 503); see ADR 0023.

### A2. Extend the deploy token

Add **Containers · Edit**, **D1 · Edit** and (for the archive) **Workers R2 Storage · Edit** to the deploy token, as in
3.1.  Nothing changes in GitHub.

### A3. Make sure the full-corpus store is uploaded

The container and the D1 backup are both built from the same store: a compressed SQLite file of 143 MB in 6 parts,
pinned by `cloud/store.json` (`sha256 ef628936…`, 958 books, 2,038,497 passages, 122,219,380 characters), uploaded
into the site's KV namespace `taochronos-store`.

**Is it there already?**  Open **Actions → site** → the latest run → job **corpus** → step *The store, from the site's
KV namespace*.  If it finished without the warning `the store cloud/store.json names is not (all) in the KV
namespace`, it is uploaded: go to A4.  (If https://chat.impf.ai/api/info already answers with the label
`全量语料（备份）`, it is uploaded and the D1 backup is live.)

**If not, upload it** (on the machine that holds the full local corpus; see the README for building it):

```bash
t=$(openssl rand -hex 32); printf %s "$t" | sha256sum      # a one-off token and its sha256; the token stays here
# GitHub → Settings → Secrets and variables → Actions → Variables: STORE_TOKEN_SHA256 = that sha256
# then Actions → site → Run workflow (the site now accepts uploads with that token)
taochronos web store                                        # writes .taochronos/cloud/<sha256>.sqlite.xz and cloud/store.json
TAOCHRONOS_STORE_TOKEN=$t taochronos web upload             # 6 parts to https://chat.impf.ai/api/store/… (parts already there are skipped)
# delete the variable STORE_TOKEN_SHA256 at once, then commit cloud/store.json and cloud/ATTRIBUTION.md if they changed
```

The upload endpoint refuses everything without a registered token, and the deployment checks every part against
`cloud/store.json`.

### A4. Build and deploy the full corpus's container

1. **Actions → site → Run workflow**, branch `main`, tick **rebuild**, **Run workflow**.
2. Job **corpus** (about 20 minutes the first time):
   - *Which version … may the account deploy containers?* — prints `deployed: none; this commit: ef628936d382-…`.
     A warning `the account may not deploy containers yet` means Workers Paid or Containers · Edit is missing (A2).
   - *Build the image and deploy the corpus Worker* — wrangler builds the image (the store unpacked, indexed and its
     caches warmed: 1.8 GB) and pushes it.
3. Job **bind** then deploys the site again, bound to the container, and runs a full-corpus search; its log ends with
   `a search on the full corpus: … ['…', '…', '…']`.
4. Check: `curl -s https://chat.impf.ai/api/info` → `"label": "全量语料"`, `"books": 958`, and no `"backup"` field.
   The first call after a new image may take a few minutes while the container starts.

Settings in `cloud/corpus/wrangler.toml` (change on `main`, then *Run workflow* with **rebuild**):

| Setting | Default | Meaning |
|---|---|---|
| `instance_type` | `standard-1` (½ vCPU, 4 GiB, 8 GB disk) | `standard-2` answers faster, costs more per hour |
| `SLEEP_AFTER` | `"15m"` | idle time before the container sleeps (billing stops); shorter is cheaper, a cold start takes tens of seconds |
| `max_instances` | `2` | research runs go to one named instance; more instances need routing work first (ADR 0023) |
| `LOCATION_HINT` | `"apac"` | where the instance lives — right for readers in Singapore and East Asia.  Fixed when the object is first created |

### A5. The D1 backup as standby (recommended, low cost)

D1 Free allowed 100,000 rows written a day, so the import was spread over two days.  **On Workers Paid there is no
daily cap** (writes are billed by the month, 50 million included), so it can finish in one run:

1. **Actions → d1 → Run workflow**, branch `main`, **budget** `1000000`, **Run workflow**.  (The budget was the Free
   plan's daily cap; on Paid it is only a safety valve.  A full import writes about 100,000 rows.)
2. A run takes up to five hours: first it writes the corpus (about 87,000 rows), then computes the precomputed results
   (about 12,000 rows).  If it stops with `the run's time is up`, run it again: it resumes where it stopped and writes
   nothing twice.  The daily run at 00:07 UTC (08:07 SGT) also resumes it.
3. When complete, the run records the version and starts the **site** workflow by itself; the site binds the
   databases (`D1_0` … `D1_4`) and sets `D1_BACKUP`.  The run's **Summary** says `complete: yes`.

With the container bound, the D1 backup stays unused; it serves when a deployment finds no container (for instance,
if a container build fails), so the full corpus never drops back to the browser's 要籍语料 for that reason.  To check
it, see §7.

*Running on D1 alone, without the container:* remove **Containers · Edit** from the token (the corpus job then skips the
build with a warning), and delete the Worker `taochronos-corpus` in the dashboard.  The site answers from D1: 14 tools
computed live, 16 precomputed, research runs not available (ADR 0017).

### A6. The archive: records out of the repository (recommended)

Until now the hourly `chat-logs` workflow commits visitors' consented conversations, and the sentinels' events (with
the addresses of flagged clients), into this repository, where they cannot be deleted from history.  With the archive,
both Workers put them in a private R2 bucket instead.

1. **R2 Object Storage → Create bucket** → name `taochronos-archive` → location *Automatic* (or *Asia-Pacific*).
   Then in the bucket's **Settings**: **Public Development URL (r2.dev)** stays **Disabled**; **Custom Domains**: none.
2. The deploy token has **Workers R2 Storage · Edit** (A2).
3. Repository variable `ARCHIVE_BUCKET` = `taochronos-archive`.
4. **Actions → relay → Run workflow**, then **Actions → site → Run workflow**.  Each deploy log shows
   `the archive: R2 bucket taochronos-archive (private): records and events are drained there …`.  A `::warning::`
   or `::error::` instead says why the bucket was not bound (not found, no permission, or possibly public); the
   Worker is deployed without it and records keep going to the repository — nothing is lost.
5. About half a minute after the next consented conversation, the bucket holds `chat-logs/YYYY/MM/DD/<id>.json`.
   The next `chat-logs` run logs `the relay archives its records in its own bucket` and commits nothing new.
6. Reading a day back (the output directory `.archive/` is ignored by git — never commit it):

   ```bash
   export LOG_EXPORT_TOKEN=…
   python3 relay/collect.py archive --day 2026-10-14            # → .archive/chat-logs/2026/10/14.jsonl
   python3 security/collect.py archive --day 2026-10-14         # → .archive/security-logs/{relay,site}/2026/10/14.jsonl
   ```

7. Retention — a decision for the publisher, to be stated in the page's consent notice.  A suggestion: conversations
   90 days, security events 30 days:

   ```bash
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive chat-logs-90d chat-logs/ --expire-days 90
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive security-30d security-logs/ --expire-days 30
   ```

To stop archiving: delete `ARCHIVE_BUCKET` and run both workflows again; the collectors resume from their cursors (ids
are never reused).  Records already committed under `data/` stay in the history; removing them is a separate decision.

### A7. The edge rules

1. Tokens 3.2 and 3.3 as secrets, `CLOUDFLARE_ZONE_ID` as a variable (§4).
2. **Actions → security → Run workflow**, action `plan`: lists what would change, writes nothing.
3. Again with action `apply`.
4. After 48 hours: **impf.ai → Security → Events**, filter on the description `[taochronos]`: no genuine visitor blocked.

The rules (`security/rules.yaml`) were written for the Free plan's limits (5 custom rules, 1 rate limit with a 10-second
window).  Workers Paid is a plan for Workers; the zone's own plan sets the WAF's limits.  If the zone moves to Pro or
higher, the rules can be extended (longer rate-limit windows, regular expressions on Business); until then they stay
as they are.

### A8. Tune for Paid

| What | Where | Recommendation |
|---|---|---|
| Sentinel mode | `SENTINEL` in `relay/wrangler.toml` and `cloud/site/wrangler.toml` | After two weeks of `observe`, read the `shadow` events; if none is a genuine visitor, set `"enforce"` in both (security/README.md, 三) |
| Model spend per visitor | `TOKENS_PER_DAY`, `PER_DAY` (relay) | Defaults: 10 M tokens and 600 calls per address a day.  Many people behind one hospital or office address share these — raise them if such users complain (sessions per visitor are the planned fix: ADR 0023) |
| Model spend in all | `TOTAL_TOKENS_PER_DAY`, `TOTAL_PER_DAY` (relay) | 200 M tokens and 5,000 calls a day: the ceiling on a bad day.  Set it from your MiniMax budget |
| Site reads and calls | `API_READS_PER_DAY`, `API_CALLS_PER_DAY` (site) | 6,000 / 3,000 per address a day; wide on purpose |
| Records waiting | `LOG_KEEP` (relay) | 50,000; when reached, new records are refused and `logs full` is logged — none dropped |
| Container | `SLEEP_AFTER`, `instance_type` | see A4 |

Each change: edit the file on `main`; the workflow redeploys.

---

## 6. Path B — a new account from nothing

1. Workers Paid on the account holding the zone (§2).
2. The three tokens (§3), the secrets and variables (§4).
3. Relay: **Actions → relay → Run workflow** (A1).  Do **not** create a DNS record for `chat-api` first: Cloudflare
   creates it and the certificate.
4. Site: if `chat.impf.ai` has a DNS record of its own (a CNAME to GitHub Pages), delete that one record in
   **impf.ai → DNS → Records** first, then **Actions → site → Run workflow**.  Within minutes the name serves HTTPS.
5. The store (A3), the container (A4), the D1 backup (A5), the archive (A6), the edge (A7), the tuning (A8).
6. Optional: GitHub → **Settings → Pages** → remove the custom domain once `chat.impf.ai` is on Cloudflare; the Pages
   site stays as a mirror at `https://psknlr.github.io/TaoChronos/`.

---

## 7. Checking the deployment

```bash
# the site: HTTPS from Cloudflare, HSTS, http redirected
curl -sI https://chat.impf.ai/ | grep -iE '^(HTTP|server|strict-transport-security)'
curl -s -o /dev/null -w '%{http_code}\n' http://chat.impf.ai/          # 301

# which corpus answers
curl -s https://chat.impf.ai/api/info | python3 -c 'import json,sys; i=json.load(sys.stdin); c=i.get("corpus",{}); print(i.get("runtime"), c.get("label"), c.get("books"), "backup" if i.get("backup") else "")'
#   container:  … 全量语料 958
#   D1 backup:  d1 全量语料（备份） 958 backup
#   neither:    an error and "corpus": "none" (the page runs the 要籍语料 in the browser)

# the default service
curl -s https://chat-api.impf.ai/v1/health
python3 relay/collect.py check                                         # one tiny model call through the relay

# what the sentinels see now (needs the collector's token)
LOG_EXPORT_TOKEN=… python3 security/collect.py summary
```

In a browser: https://chat.impf.ai shows a lock; ask 「桂枝汤的组成出自哪部书？」; the answer's citations open on a
click; **设置 → 关于** links to the full corpus's sources.

Cloudflare dashboard: **Workers & Pages** lists `taochronos-site`, `taochronos-relay`, `taochronos-corpus`; each has
**Metrics** and **Logs**.  **Storage & Databases → D1** lists `taochronos-d1-0` … `-4`; **R2** the archive bucket.

---

## 8. What runs on its own

| Workflow | When (UTC / SGT) | Does |
|---|---|---|
| `relay` | on a push to `main` touching `relay/` or `security/` | test, deploy, check the relay |
| `site` | on a push to `main` touching the site, the code, the corpus or `security/` | test, deploy the site; build the container when its inputs changed; bind and check |
| `chat-logs` | hourly at :17 (same minute in SGT) | collect records and sentinel events into the repository — from a Worker without the archive only |
| `d1` | daily 00:07 UTC / 08:07 SGT | resume or check the D1 import |
| `security` | daily 01:41 UTC / 09:41 SGT; on a push of `security/blocklist.yaml` | pull the edge's events; write the block list |
| `pages` | on a push to `main` touching the web client | the GitHub Pages mirror |
| `ci` | every push and pull request | Python and Worker tests |

Inside the Workers: the archive's alarms (half a minute after a record or a flagged event); the container sleeps after
`SLEEP_AFTER`.

---

## 9. Costs and the guards on them

Cloudflare bills Workers Paid in US dollars: 5 USD a month plus usage beyond each product's allowance.  The figures below
are Cloudflare's published ones at the time of writing — check the pricing pages
([Workers](https://developers.cloudflare.com/workers/platform/pricing/),
[Containers](https://developers.cloudflare.com/containers/pricing/), [D1](https://developers.cloudflare.com/d1/platform/pricing/),
[Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/), [R2](https://developers.cloudflare.com/r2/pricing/))
before relying on them.

| Item | Included each month | This site's use |
|---|---|---|
| Workers requests / CPU | 10 M requests, 30 M CPU-ms | only pages and `/api/*` pass through a Worker; static files are free |
| Containers | 25 GiB-h memory, 375 vCPU-min, 200 GB-h disk | `standard-1` about 0.036 USD per running hour: ~4 USD/month at 4 h a day, ~30 USD if it never sleeps |
| D1 | 25 bn rows read, 50 M rows written, 5 GB storage | ~1.5 GB stored; one import ~100 k rows written |
| Durable Objects | 1 M requests (plus duration and SQLite storage allowances) | a few per API call or model call |
| Workers KV | 1 GB storage | the store, 143 MB |
| R2 | 10 GB-month, 1 M Class A, 10 M Class B operations | one write per record or event |
| **MiniMax** (not Cloudflare) | your balance | the largest cost by far; bounded by the relay's limits (A8) |

Guards: the relay's token and call limits (per address and in all, per day); the site's daily caps; the container's
sleep; the sentinel.  Billing alerts are not caps: set one anyway in **Notifications → Add → Billing** (usage-based
billing, where your account offers it) and keep the MiniMax balance at what you are willing to spend.

---

## 10. Day-to-day operations

| Task | How |
|---|---|
| Rotate the MiniMax key | New key in MiniMax → update secret `MINIMAX_API_KEY` → **Actions → relay → Run workflow** → when the check passes, delete the old key |
| Rotate the deploy token | Create a new one (3.1) → update `CLOUDFLARE_API_TOKEN` → run **relay** and **site** → delete the old token |
| Rotate the collector token | New random string → update `LOG_EXPORT_TOKEN` → run **relay** and **site** |
| Update the full corpus | A3 with a new store; merging the new `cloud/store.json` rebuilds the container; the d1 workflow re-imports (the old databases are replaced) |
| Change limits or modes | edit the `[vars]` in the Worker's `wrangler.toml` on `main` |
| Stop recording conversations | `LOGS = "off"` in `relay/wrangler.toml`; the page stops asking |
| Pause the default service | Dashboard → `taochronos-relay` → **Settings → Variables and Secrets** → delete `MINIMAX_API_KEY`; the page asks visitors for their own key.  Run **relay** to restore |
| Block an address now | Dashboard → **Manage Account → Configurations → Lists → `taochronos_block`**; then add it to `security/blocklist.yaml` |
| See the sentinels | `LOG_EXPORT_TOKEN=… python3 security/collect.py summary` |
| Read archived records | §A6 step 6 |

---

## 11. Rolling back

- **A Worker**: Dashboard → **Workers & Pages** → the Worker → **Deployments** → an earlier version → **Rollback**; or
  revert the commit on `main` and let the workflow deploy.  This release adds no Durable Object migration, so rolling
  the relay or the site back over it is safe.  Records the archive has not yet drained stay in the relay and are
  collected again by the repository once the bucket is unbound.
- **The container**: run **site** with **rebuild** from an earlier commit (Run workflow → choose the branch or tag).
- **Back to GitHub Pages** (last resort): remove `chat.impf.ai` under the site Worker's **Domains & Routes**; add a
  CNAME `chat` → `psknlr.github.io`, **DNS only**; set the custom domain under the repository's **Settings → Pages**.

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| relay: `the relay is not deployed until these repository secrets are set: …` | a secret missing or misnamed | add it exactly as named (§4), run again |
| `Authentication error [code: 10000]` | token permissions or account wrong | check `CLOUDFLARE_ACCOUNT_ID`; edit the token (3.1) |
| `No access to the specified resource` (`workers/routes`) | the token's Zone Resources lack `impf.ai` | edit the token: add the zone |
| site: `externally managed DNS records` | `chat` has a DNS record of the account's own | delete that record (§6, step 4), run **site** at once |
| corpus: `the account may not deploy containers yet` | no Workers Paid, or no Containers · Edit | A2, then **site** with **rebuild** |
| corpus: `the store … is not (all) in the KV namespace` | store not uploaded | A3 |
| corpus: `container was not deployed` | the build or deploy failed (error in the step above) | fix, run **site** with **rebuild** |
| d1: `the API token may not use D1` | no D1 · Edit | A2, run **d1** |
| d1 stops: `the day's budget` | the budget given (90,000 on the daily run) was reached; runs of one UTC day count together | run again with budget `1000000` |
| d1 stops: `the run's time is up` | five hours used | run again; it resumes |
| `/api/info` → 503 `corpus: none` | neither container nor D1 backup bound | check the corpus and d1 runs; then run **site** |
| visitors see 「该地址因异常访问已被暂时限制」 | the sentinel refused the address (403) | read its events; if a mistake, shorten `BLOCK_SECONDS` or return `SENTINEL` to `observe` |
| visitors see 「今天的查询次数已用完」 | the address's daily cap (429) | raise `API_READS_PER_DAY` / `API_CALLS_PER_DAY` if genuine |
| relay check: `MiniMax refused the key … api.minimax.io` | international key with the mainland address (or the reverse) | `UPSTREAM_BASE` in `relay/wrangler.toml` (A1.3) |
| Workers Logs: `logs full` | records not collected for a long while | check the `chat-logs` runs; with the archive, look for `archive … Error` lines |
| deploy: `the archive's bucket … may be public` | r2.dev on, a custom domain, or the token cannot read them | turn r2.dev off, remove domains, check R2 permission; run again |
| `chat-logs`: `the records could not be pushed` | `main` protected against Actions | allow GitHub Actions to push, or use the archive (A6) |
| `chat-logs`: `the relay refused the export: HTTP 401` | `LOG_EXPORT_TOKEN` differs between GitHub and the Worker | run **relay** (and **site**) to write it again |

---

## 13. Reference: files and workflows

| Path | What |
|---|---|
| `relay/wrangler.toml`, `relay/src/` | the default service (limits, sentinel mode, records) |
| `cloud/site/wrangler.toml`, `cloud/site/src/`, `cloud/site/deploy.sh` | the site and its deployment (bindings added for what the account has) |
| `cloud/corpus/wrangler.toml`, `cloud/corpus/Dockerfile` | the full corpus's container |
| `cloud/store.json` | the store deployed |
| `security/sentinel.js`, `security/archive.js`, `security/bind-archive.sh` | the sentinel, the archive, the bucket check |
| `security/rules.yaml`, `security/blocklist.yaml` | the edge rules and the block list |
| `relay/collect.py`, `security/collect.py` | the repository's collectors (pull, ack, archive, summary, check) |
| `.github/workflows/` | `relay`, `site`, `d1`, `chat-logs`, `security`, `pages`, `canon`, `ci` |
