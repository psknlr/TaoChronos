# Hashed lockfiles

`pyproject.toml` says which releases taochronos works with; the files here say which ones are installed.  Each pins
every package — direct and transitive — to one version, with the sha256 of each of its files on PyPI, so
`pip install --require-hashes -r requirements/<file>.txt` installs exactly those bytes or nothing (a changed or
substituted file fails the install).  They are universal: one file serves Linux, macOS and Windows and Python 3.11 and up.

| File | Holds | Installed by |
|---|---|---|
| `runtime.txt` | the package's own dependencies (PyYAML) | the full corpus's image (`cloud/corpus/Dockerfile`), the workflows that build the site, the store and the alias layer |
| `build.txt` | what builds it: `pyproject.toml`'s `[build-system]` (`build.in`) | the same, before `pip install --no-deps --no-build-isolation`, so the build fetches nothing unpinned |
| `dev.txt` | runtime + `dev` + `anthropic` | CI's tests (`.github/workflows/ci.yml`) |
| `litellm.txt` | runtime + `litellm` | the LiteLLM provider, kept apart: its tree is 59 packages |
| `ingest.txt` | runtime + `pdf` + `parquet` | the 東亜医学協会 PDF and Hugging Face Parquet ingesters |
| `audit.txt` | pip-audit (`audit.in`) | the audit workflow, which reads every file here against the advisories |
| `native.txt` | maturin (`native.in`): what builds TaoCore's CPython extension, its own distribution (`rust/crates/taocore-py`) | CI's `native` job and the full corpus's image; taochronos itself never needs it |

A local install that matches CI:

```bash
pip install --require-hashes -r requirements/build.txt -r requirements/dev.txt
pip install --no-deps --no-build-isolation -e .
```

## Regenerating

`requirements/lock.sh` (needs [uv](https://docs.astral.sh/uv/)) after a change to `pyproject.toml` or `constraints.in`:
the pins stay where they still fit.  `requirements/lock.sh --upgrade` re-resolves everything to the newest releases the
ranges allow; `requirements/lock.sh --upgrade NAME…` moves only the packages named — to the newest release allowed, or
to the one given (`pypdf==6.21.4`) — and keeps every other pin; `requirements/lock.sh --check` fails if a file no
longer matches `pyproject.toml`.  The audit workflow (`.github/workflows/audit.yml`) reads every file here against the
public advisory databases each week, and on any change to them.

When the audit fails, it names the package, the advisory and the release that fixes it.  For a direct requirement,
raise its lower bound in `pyproject.toml` to that release (the table below, and `FLOORS` in
`tests/test_supply_chain.py`); then `requirements/lock.sh --upgrade NAME` for each package named, and the audit's own
check over the result:

```bash
python -m venv /tmp/audit && /tmp/audit/bin/pip install --require-hashes -r requirements/audit.txt
```

```bash
for f in requirements/*.txt; do sed -E 's/^([A-Za-z0-9._-]+==[^ ;]+) ;[^\\]*/\1 /' "$f" > /tmp/all.txt; /tmp/audit/bin/pip-audit --strict --progress-spinner off --disable-pip --require-hashes -r /tmp/all.txt; done
```

## The lower bounds

Each lower bound in `pyproject.toml` is the first release from which no published advisory applies (OSV's PyPI data of
2026-10-28; counts with aliases folded), so that an install looser than these files — `pip install taochronos[…]` —
cannot pick a release with a known vulnerability.  The security assessment of 2026-10-26 found that five of the seven
old bounds allowed such releases.

| Requirement | Was | Now | Why |
|---|---|---|---|
| `setuptools` (build) | `>=68` | `>=84.1.0` | 4 advisories at 68, two of them high: CVE-2024-6345 (command injection through a package URL) and CVE-2025-47273 (path traversal in `PackageIndex.download`) |
| `wheel` (build) | any | `>=0.46.2` | CVE-2022-40898 (ReDoS) before 0.38.1; GHSA-8rrh-rw8j-w5fx (file permissions changed through path traversal in `wheel unpack`, high) before 0.46.2 |
| `litellm` | `>=1.40` | `>=1.103.1` | 31 advisories at 1.40, 4 critical (an authentication bypass through the Host header among them, CVE-2026-49468) and 12 high; the last, GHSA-7hp6-4w63-5g45 (CVE-2026-114612: privilege escalation to proxy admin, high), is fixed on the 1.103 line in 1.103.1 |
| `pytest` | `>=8` | `>=9.0.3` | CVE-2025-71176 (its temporary directories' handling) |
| `pyarrow` | `>=14` | `>=23.0.1` | CVE-2023-47248 (code execution loading a crafted data file, critical) before 14.0.1; CVE-2024-52338 before 17.0.0 (PYSEC lists it against pyarrow; its text names Arrow's R package); CVE-2026-25087 (use-after-free reading IPC files, high) from 15.0.0 before 23.0.1 |
| `pypdf` | `>=4` | `>=6.21.4` | 60 advisories at 4.0, 13 of them high: mostly endless loops and memory exhaustion on crafted PDFs; three more of the kind since (GHSA-5849-834g-hvw5, GHSA-mfr5-77xh-9j7h, GHSA-cggf-277g-3q54), fixed in 6.21.4 |
| `PyYAML`, `anthropic` | `>=6.0`, `>=1.0` | unchanged | no advisory applies |

## filelock: held at 3.20.3, then released

The assessment's one finding in a resolved environment was filelock 3.32.7 (pulled in by litellm): GHSA-v4x8-3wr5-3wq8
(CVE-2026-112940, high), GHSA-9vhv-jxww-xfm5 and GHSA-567q-5qvw-pf92 (low), all fixed in 4.2.1 — which no litellm
release then allowed (`filelock<4.0`).  3.20.3 was the one release under 4 with no advisory, so `constraints.in` held
the LiteLLM environment there.  Two advisories were then published against 3.20.3 itself — GHSA-69hj-f68j-2879
(CVE-2026-112909: on Unix the lock empties a regular file it finds at its path) and GHSA-8mx5-7m5m-r77g
(CVE-2026-112910: `mode` ignored on Windows), fixed in 4.2.1 too — and litellm allows `filelock<5` from 1.106.12 on the
line pinned here (1.108.3 on the next).  So the hold is gone: `litellm.txt` has litellm 1.106.12, and it and `audit.txt`
(pip-audit's cache) have filelock 4.3.1, with no advisory.  Nothing in this project or its LiteLLM tree uses
`ReadWriteLock`, which the high one needs.

Two transitive pins moved for an advisory of their own at the same time: opentelemetry-api 1.45.2 in `dev.txt` (through
anthropic; GHSA-mf5v-w3w3-f6cg, a regular expression that backtracks on a crafted trace header), and pypdf above.
