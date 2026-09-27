"""PubMed through NCBI E-utilities (esearch, esummary, efetch): searches and records, cached, polite.

Requests carry the tool name (and ``NCBI_API_KEY`` / ``NCBI_EMAIL`` when the user sets them — nothing else is sent);
they are spaced (three a second, ten with a key), retried on 429 and 5xx with backoff, and every answer is cached under
the data directory, so a query asked twice costs one request and a result can be re-read offline.  ``opener`` replaces
the network in tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedError(RuntimeError):
    pass


class PubMed:
    def __init__(self, cache_dir: str | Path, *, opener: Callable[[str], bytes] | None = None, timeout: float = 30.0,
                 retries: int = 3, online: bool = True) -> None:
        self.cache_dir = Path(cache_dir)
        self.opener = opener
        self.timeout = timeout
        self.retries = retries
        self.online = online
        self.api_key = os.environ.get("NCBI_API_KEY")
        self.email = os.environ.get("NCBI_EMAIL")
        self._last = 0.0
        self.requests = 0

    # ------------------------------------------------------------ transport
    def _url(self, endpoint: str, params: dict[str, Any]) -> str:
        q = {**params, "tool": "taochronos"}
        if self.email:
            q["email"] = self.email
        return f"{EUTILS}/{endpoint}.fcgi?" + urllib.parse.urlencode(q)

    def _get(self, endpoint: str, params: dict[str, Any]) -> bytes:
        url = self._url(endpoint, params)
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self.cache_dir / key[:2] / key
        if path.exists():
            return path.read_bytes()
        if not self.online:
            raise PubMedError("offline and not cached")
        full = url + (f"&api_key={self.api_key}" if self.api_key else "")  # the key is never cached in the URL hash
        err: Exception | None = None
        for attempt in range(self.retries):
            wait = (0.11 if self.api_key else 0.34) - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                self.requests += 1
                if self.opener is not None:
                    data = self.opener(url)
                else:
                    req = urllib.request.Request(full, headers={"User-Agent": "TaoChronos/0.1 (research harness)"})
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        data = resp.read()
                if endpoint == "esearch":
                    body = json.loads(data.decode("utf-8"))
                    if (body.get("esearchresult") or {}).get("ERROR"):
                        raise PubMedError(body["esearchresult"]["ERROR"][:200])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return data
            except urllib.error.HTTPError as exc:
                err = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, PubMedError) as exc:
                err = exc
            time.sleep(min(8.0, 1.5 * 2 ** attempt))
        raise PubMedError(f"{endpoint} failed: {err}")

    # ------------------------------------------------------------ API
    def search(self, term: str, *, retmax: int = 20, sort: str = "relevance") -> list[str]:
        data = self._get("esearch", {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json", "sort": sort})
        return list(json.loads(data.decode("utf-8"))["esearchresult"].get("idlist", []))

    def summaries(self, pmids: list[str]) -> list[dict[str, Any]]:
        if not pmids:
            return []
        data = json.loads(self._get("esummary", {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}).decode("utf-8"))
        res = data.get("result", {})
        out = []
        for uid in res.get("uids", []):
            r = res[uid]
            doi = next((a["value"] for a in r.get("articleids", []) if a.get("idtype") == "doi"), None)
            year = None
            for token in str(r.get("pubdate", "")).split():
                if token[:4].isdigit():
                    year = int(token[:4])
                    break
            out.append({"pmid": uid, "title": r.get("title", ""), "journal": r.get("fulljournalname", ""), "year": year,
                        "publication_types": list(r.get("pubtype", [])), "doi": doi})
        return out

    def abstracts(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        """Abstract text and MeSH headings by PMID (efetch XML)."""
        if not pmids:
            return {}
        root = ET.fromstring(self._get("efetch", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}))
        out: dict[str, dict[str, Any]] = {}
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            abstract = " ".join("".join(t.itertext()) for t in art.iter("AbstractText"))
            mesh = [d.text or "" for d in art.iter("DescriptorName")]
            pts = [p.text or "" for p in art.iter("PublicationType")]
            out[pmid] = {"abstract": abstract, "mesh": mesh, "publication_types": pts}
        return out


__all__ = ["EUTILS", "PubMed", "PubMedError"]
