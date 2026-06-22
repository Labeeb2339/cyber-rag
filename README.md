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

# prove the thesis
python eval/run_eval.py --judge           # local-only vs CyberRAG, with scores
python eval/run_eval.py --cloud --judge   # full A/B/C vs cloud ceiling
```

## Success criteria

- CyberRAG **beats local-only** decisively → RAG supplies the missing expertise.
- CyberRAG lands **within a small margin of cloud** → the gap is bridged.
- **Zero egress** during queries → verifiable by running with the NIC disabled.

## Project layout

```
cyber-rag/
├── corpus/          authoritative source docs (attack/kev/capec/sigma)
├── ingest/          fetch_authoritative.py, build_index.py
├── rag/             hybrid.py (retrieval), kg.py (graph), engine.py (unified)
├── eval/            questions.json, run_eval.py, results_*.json
├── data/            chroma/ (vectors), bm25.pkl, attack_kg.pkl
├── demo.py          interactive CLI
└── docs/ARCHITECTURE.md
```
