# CyberRAG — Executive Brief

**For:** CyberSec Malaysia
**One line:** A fully-local AI threat-intelligence analyst that matches cloud-model quality on cybersecurity questions while guaranteeing **no sensitive data ever leaves your network**.

---

## The problem

Security teams want to use LLMs for threat intel, alert triage, and analyst
augmentation. But they're stuck between two bad options:

- **Cloud models (GPT, Claude):** powerful, but every query — internal IOCs,
  victim data, incident details — is sent to a third-party provider. For a
  CERT/SOC handling classified material, that's a non-starter.
- **Local open models:** private and cheap, but they lack security domain
  expertise and **hallucinate** CVE numbers, ATT&CK technique IDs, and threat
  attributions — dangerous in an intelligence product.

## The solution: CyberRAG

Give a small **local** model the domain expertise it lacks by grounding every
answer in an authoritative cybersecurity knowledge base — retrieved locally,
generated locally, cited inline. Result: cloud-level answers, zero egress, ~$0
marginal cost.

## Three things that make it credible (not a demo toy)

1. **Authoritative corpus** — MITRE ATT&CK (858 techniques), CISA KEV (1,623
   exploited CVEs), CAPEC (615 patterns), Sigma (1,340 detection rules), plus
   825+ practical exploitation playbooks. ~5,200 docs / 13,000+ searchable chunks.
2. **Hybrid retrieval + knowledge graph** — vector + keyword (BM25) + rank-fusion
   + rerank for accuracy, PLUS a NetworkX graph over ATT&CK (2,139 nodes / 18,984
   edges) for multi-hop questions vector search can't answer (*"which techniques
   does APT29 use and how do I detect them?"*).
3. **Measured, not claimed** — an evaluation harness scores local-only vs CyberRAG
   vs a cloud ceiling on the same question set, judged by an independent cloud
   model. (Numbers in the results section once the run completes.)

## Why local RAG is *more secure*, not just cheaper

Per the 2025 arXiv study *"Securing RAG: A Risk Assessment and Mitigation
Framework"*, cloud-hosted RAG carries risk classes CyberRAG **eliminates by
construction**: prompt disclosure to a third-party LLM (R7), retrieval data
leakage (R2), and embedding inversion by an external party (R3). When the model,
the index, and the embeddings all live on your host, those attack surfaces don't
exist.

## Deploy it on your own data

The headline feature for an operational team: drop your own **PDFs / Word docs /
text** (threat advisories, incident reports, pentest findings) into a folder,
ingest them locally, and query them immediately — auto-tagged with the ATT&CK
techniques and CVEs found inside, retrieved and cited alongside the public corpus.
Nothing is uploaded anywhere.

## Hardware reality

Runs on a single laptop with an 8GB GPU (`qwen2.5-coder:7b` at ~34 tok/s). No
cluster, no GPUs farm, no per-query API bill. Scales down to commodity hardware a
Malaysian agency or SME already owns.

---

*Built by Muhammad Labeeb Aryan (Team Powerpuff Girls) — local-first security AI.*
