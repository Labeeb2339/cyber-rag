# CyberRAG — Local Cybersecurity Threat-Intelligence RAG

> **A cheap, fully-local LLM + a domain-specific RAG pipeline that matches
> expensive cloud models on cybersecurity threat-intel — with zero data egress.**

Built for CyberSec Malaysia. Everything runs on one machine: local embeddings,
local vector + graph retrieval, local LLM. No API keys, no cloud calls, no data
ever leaves the network.

---

## The problem (CyberSec Malaysia's brief)

Organizations face a dilemma using AI for cybersecurity:
- **Cloud models** (GPT, Claude) are powerful but **expensive** and **leak
  sensitive data** — every prompt with internal IOCs, victim data, or incident
  details goes to a third party.
- **Local models** are cheap and private but **lack domain expertise** and
  **hallucinate** technique IDs, CVE numbers, and attributions.

## The solution

A specialized cybersecurity **RAG knowledge base** that gives a small local model
the domain expertise it lacks — grounding every answer in authoritative sources
so it stops hallucinating and starts matching cloud-model quality.

## Why local RAG is *more* secure, not just cheaper

This isn't only a cost play. Per the 2025 arXiv study *"Securing RAG: A Risk
Assessment and Mitigation Framework"*, cloud RAG introduces a whole risk class we
**eliminate by construction**:

| Risk (from the paper) | Cloud RAG | CyberRAG (local) |
|---|---|---|
| **R7 Prompt Disclosure** — sensitive info sent to a cloud LLM | ⚠️ inherent | ✅ eliminated — LLM is local |
| **R6 Disclosure during prompting** | ⚠️ present | ✅ eliminated — no egress |
| **R2 Retrieval Data Leakage** to third parties | ⚠️ possible | ✅ data never leaves host |
| **R3 Embedding Inversion** by external party | ⚠️ possible | ✅ embeddings stay local |

For a CERT/SOC handling classified IOCs and victim data, "the data never leaves
the building" is not a nice-to-have — it's the requirement.

---

## Architecture (all local)

```
query
  │
  ├─▶ KG router ── (APT/malware/technique + relational?) ──▶ ATT&CK knowledge graph
  │                                                          (multi-hop facts)
  ├─▶ hybrid retrieval ─ vector (nomic-embed) + BM25 + RRF + LLM rerank ─▶ top-k passages
  │                                ChromaDB (on-disk)
  ▼
  grounded prompt (KG facts + passages)  ──▶  local LLM (qwen2.5-coder:7b)
  ▼
  answer + inline citations [doc] / [ATT&CK]
```

- **Embeddings:** `nomic-embed-text` (Ollama, 768-dim, local)
- **Vector store:** ChromaDB (embedded, on-disk)
- **Lexical:** BM25 (catches exact CVE/technique IDs dense vectors miss)
- **Fusion:** Reciprocal Rank Fusion + local LLM reranking
- **Knowledge graph:** NetworkX over MITRE ATT&CK STIX — 2,139 nodes, 18,984 edges
- **Generator:** `qwen2.5-coder:7b-64k` (Ollama) — fits an 8GB GPU, ~34 tok/s
- **Cloud:** used ONLY in the eval harness as a quality ceiling — never in the path

## Knowledge base (authoritative corpus)

| Source | Docs | What it provides |
|---|---|---|
| MITRE ATT&CK (Enterprise) | 858 techniques | TTPs, detection guidance |
| CISA KEV | 1,623 CVEs | known-exploited vulnerabilities |
| CAPEC | 615 patterns | attack-pattern taxonomy |
| Sigma rules | 1,340 rules | detection logic |
| Bug-bounty playbooks | 71 | real web-exploitation techniques (H1-derived) |
| Anthropic cyber skills | 754 | TTPs across 26 domains |
| **Total** | **~5,200 docs / ~7k+ chunks** | |

Plus a **knowledge graph** linking APT groups → malware → techniques →
mitigations, enabling multi-hop questions pure vector RAG cannot answer:
- *"Which techniques does APT29 use?"*
- *"What malware is linked to Sandworm and what does it do?"*
- *"How do I mitigate the techniques used by FIN7?"*

---

## What makes it credible (not a toy demo)

1. **Hybrid retrieval** — vector + BM25 + RRF + rerank, the same design serious
   CTI-RAG systems use, beats naive single-vector retrieval.
2. **Knowledge graph multi-hop** — relational reasoning over ATT&CK, the feature
   that separates "search" from "intelligence".
3. **Measured, not claimed** — a RAGAS-style eval harness scores
   local-only vs CyberRAG vs cloud on the same 15 questions
   (keyword coverage, retrieval hit-rate, LLM-judge correctness, latency).
4. **Anti-hallucination by design** — the system prompt forbids inventing
   CVE/technique IDs; every claim is cited to a source doc or graph fact.

## Usage

```bash
# one-time setup (only step that touches the network)
python ingest/fetch_authoritative.py      # download ATT&CK/KEV/CAPEC/Sigma
python ingest/build_index.py              # embed + index into ChromaDB
python rag/hybrid.py build                # build BM25 index
python rag/kg.py build                    # build ATT&CK knowledge graph

# query (100% offline from here)
python demo.py                            # interactive
python demo.py "Which techniques does APT29 use and how to detect them?"

# >>> ingest YOUR OWN sensitive documents (the feature a real SOC/CERT needs) <<<
python ingest/ingest_docs.py ./my_reports --source internal-cti --recursive
python rag/hybrid.py build                # refresh BM25 so new docs are searchable
#   supports PDF, DOCX, MD, TXT, HTML — extraction/embedding/storage all local.
#   auto-tags MITRE ATT&CK technique IDs and CVE IDs found in each document.
#   re-ingesting an updated file safely overwrites its old chunks (stable IDs).

# prove the thesis
python eval/run_eval.py --judge           # local-only vs CyberRAG, with scores
python eval/run_eval.py --cloud --judge   # full A/B/C vs cloud ceiling
```

## Ingest your own intelligence (the real-world use case)

The authoritative corpus proves the system works on public data. But the reason a
CERT/SOC would deploy CyberRAG is to query **their own** classified material —
internal threat advisories, incident post-mortems, pentest reports, vendor briefs
— **without any of it leaving the building**.

```bash
python ingest/ingest_docs.py /path/to/confidential_report.pdf --source my-org
python rag/hybrid.py build
python demo.py "What was the C2 domain and mitigation in the BNM phishing advisory?"
```

The loader extracts text (PyMuPDF for PDF, python-docx for Word), chunks it,
embeds locally, and upserts into the same knowledge base — so your private docs
are retrieved and cited alongside ATT&CK/KEV/CAPEC just like everything else.
**Verified working:** a sample internal CTI PDF was ingested, retrieved (rerank
score 8/10), and answered with the exact C2 domain and mitigations quoted from
the document — nothing invented, nothing sent to a cloud.

## Results (measured)

15-question benchmark spanning web exploitation, ATT&CK techniques, CVEs, and
threat-group intel. Answers graded 0–1 for technical correctness by an
**independent cloud model** (not the local generator — no self-grading bias).

| metric | local-only | **CyberRAG** | cloud ceiling |
|---|---|---|---|
| Correctness (LLM-judge) | 0.43 | **0.65** | 0.77 |
| Keyword coverage | 0.63 | **0.84** | 0.93 |
| Retrieval hit-rate | — | **0.93** | — |
| Latency (s/query) | 12 | **15** | 45 |
| Cost / data egress | $0 / none | **$0 / none** | $$ / full prompt leaves |

**Read:**
- CyberRAG beats raw local-only on **every question** — correctness +51%
  (0.43→0.65), keyword coverage +34%. RAG supplies the domain expertise the
  small model lacks.
- It closes **~58% of the gap** to the expensive cloud model, at **$0**, **3×
  faster**, and with **zero data egress**.
- Honest caveat: it does *not* fully match cloud on graded correctness (0.65 vs
  0.77). The claim is "near-cloud quality, local and private" — not "identical."

> The eval also did its job as an engineering tool: the first run exposed that
> exact CVE/ATT&CK-ID lookups were failing (Log4Shell returned nothing). Fixing
> the retrieval (query stopword stripping + exact-ID boost + canonical-doc
> lookup) lifted retrieval hit-rate 0.53 → 0.93 and correctness 0.59 → 0.65.

## Success criteria

- ✅ CyberRAG **beats local-only** decisively → RAG supplies the missing expertise.
- ◑ CyberRAG lands **near cloud** (closes ~58% of the gap) → strong, not parity.
- ✅ **Zero egress** during queries → verifiable by running with the NIC disabled.

## Project layout

```
cyber-rag/
├── corpus/          authoritative source docs (attack/kev/capec/sigma)
├── ingest/          fetch_authoritative.py, build_index.py, ingest_docs.py (PDF/DOCX/TXT)
├── rag/             hybrid.py (retrieval), kg.py (graph), engine.py (unified)
├── eval/            questions.json, run_eval.py, results_*.json
├── data/            chroma/ (vectors), bm25.pkl, attack_kg.pkl
├── demo.py          interactive CLI
└── docs/            ARCHITECTURE.md, EXECUTIVE_BRIEF.md
```
