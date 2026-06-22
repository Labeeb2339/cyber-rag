# CyberRAG — Local Cybersecurity Threat-Intelligence RAG

**For:** CyberSec Malaysia
**Built by:** HiddenTrojan (Labeeb)
**Date started:** 2026-06-22

## The thesis (what we're proving)

> A cheap, **fully-local** model + a domain-specific RAG pipeline can match the
> analytical quality of expensive cloud models on cybersecurity threat-intel
> tasks — **without any data leaving the network.**

Three things must be true at the end:
1. **Local & private** — no API calls, no data egress. Everything runs on the box
   (Ollama LLM + local embeddings + local vector DB).
2. **Accurate** — RAG-grounded answers cite real sources and don't hallucinate.
3. **Competitive** — measurably closes the gap vs a cloud model (Claude/GPT) on
   the same questions, shown with numbers, not vibes.

## Architecture (all local)

```
                 ┌─────────────────────────────────────────────┐
                 │              CyberRAG (offline)               │
                 │                                               │
  query ──▶ embed (nomic-embed-text, Ollama) ──▶ vector search   │
                 │                    │                          │
                 │              ChromaDB (local, on-disk)        │
                 │                    │                          │
                 │            top-k chunks + metadata            │
                 │                    │                          │
                 │   prompt(query + retrieved context) ──▶ LLM   │
                 │              qwen2.5-coder:7b (Ollama)        │
                 │                    │                          │
                 └────────────────────┼──────────────────────────┘
                                       ▼
                          grounded answer + citations
```

- **Embeddings:** `nomic-embed-text` via Ollama (local, 768-dim, fast, free).
- **Vector store:** ChromaDB (embedded, on-disk at `data/chroma/`, no server).
- **Generator:** `qwen2.5-coder:7b-64k` via Ollama (fits the 8GB GPU, 34 tok/s).
- **Baseline for comparison:** a cloud model (Claude/GPT via Nous Portal) — used
  ONLY in the eval harness to score the gap, never in the production path.

## Corpus (the domain knowledge)

Starting material already on this machine — no scraping needed for v1:
| Source | Items | What it gives |
|---|---|---|
| Anthropic-Cybersecurity-Skills | 754 SKILL.md | TTPs across 26 domains, mapped to MITRE ATT&CK/NIST |
| Claude-BugHunter | 71 SKILL.md | bug-bounty/web-exploitation playbooks from real H1 reports |
| MITRE ATT&CK quick-ref | 1 | tactic/technique taxonomy |
| Threat-intel reports/IOCs | latest.json | live MY-focused IOC context |

Expandable later: CVE/NVD dumps, CISA KEV, MITRE ATT&CK full STIX, vendor advisories.

## Pipeline stages

1. **`ingest/`** — load corpus → chunk (markdown-aware, ~512 tokens, overlap) →
   embed → store in Chroma with metadata (source, domain, ATT&CK id).
2. **`rag/`** — query → embed → retrieve top-k → build grounded prompt →
   generate with local LLM → return answer + citations.
3. **`eval/`** — a fixed question set; score **local+RAG** vs **local-only** vs
   **cloud** on the same questions. Metrics: retrieval hit-rate, answer
   correctness (LLM-judge + keyword), citation validity, hallucination rate,
   latency, cost.

## Success criteria (the demo)
- Local+RAG **beats local-only** decisively (proves RAG adds the domain expertise).
- Local+RAG lands **within a small margin of cloud** (proves the gap is bridged).
- **Zero network egress** during a production query (proven by running with
  network disabled / monitoring no outbound calls).

## Stack
- Python 3.11 + uv venv
- `chromadb`, `ollama` (python client), `langchain-text-splitters` (chunking only),
  `tiktoken`, `rich` (CLI), `pytest` (eval)
- No cloud dependency in the core path.

## Status
- [x] Project scaffold
- [ ] Pull `nomic-embed-text` (in progress)
- [ ] Ingest pipeline
- [ ] RAG query pipeline
- [ ] Eval harness + question set
- [ ] Demo run + writeup for CyberSec Malaysia
