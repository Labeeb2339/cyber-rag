#!/usr/bin/env python3
"""
Hybrid retrieval for CyberRAG — vector + BM25 + reciprocal-rank fusion + LLM rerank.

Why hybrid: dense vectors catch semantic matches; BM25 catches exact terms (CVE
IDs, technique IDs, tool names) that embeddings often miss. RRF fuses both rank
lists; an optional LLM rerank promotes the truly relevant chunks to the top.
All local. Supports source_filter (e.g. ['mitre-attack','cisa-kev']).
"""
import os
import re
import pickle

import chromadb
import ollama
from rank_bm25 import BM25Okapi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(ROOT, "data", "chroma")
BM25_PATH = os.path.join(ROOT, "data", "bm25.pkl")
COLLECTION = "cyber_kb"
EMBED_MODEL = "nomic-embed-text"
GEN_MODEL = "qwen2.5-coder:7b-64k"

_tok = re.compile(r"[A-Za-z0-9_.\-]+")


def tokenize(text):
    return [t.lower() for t in _tok.findall(text)]


def build_bm25():
    """One-time: pull all docs from Chroma, build a BM25 index, pickle it."""
    col = chromadb.PersistentClient(path=CHROMA_DIR).get_collection(COLLECTION)
    got = col.get(include=["documents", "metadatas"])
    docs = got["documents"]
    ids = got["ids"]
    metas = got["metadatas"]
    bm25 = BM25Okapi([tokenize(d) for d in docs])
    with open(BM25_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "ids": ids, "docs": docs, "metas": metas}, f)
    print(f"[bm25] built over {len(docs)} chunks -> {BM25_PATH}")


_cache = {}


def _load_bm25():
    if "bm25" not in _cache:
        with open(BM25_PATH, "rb") as f:
            _cache["bm25"] = pickle.load(f)
    return _cache["bm25"]


def _col():
    if "col" not in _cache:
        _cache["col"] = chromadb.PersistentClient(path=CHROMA_DIR).get_collection(COLLECTION)
    return _cache["col"]


def vector_search(query, k, source_filter=None):
    qemb = ollama.embeddings(model=EMBED_MODEL, prompt=query)["embedding"]
    where = {"source": {"$in": source_filter}} if source_filter else None
    res = _col().query(query_embeddings=[qemb], n_results=k, where=where,
                       include=["documents", "metadatas", "distances"])
    out = []
    for i, (doc, meta, dist) in enumerate(zip(res["documents"][0], res["metadatas"][0], res["distances"][0])):
        out.append({"id": res["ids"][0][i], "doc": doc, "meta": meta, "vscore": 1 - dist})
    return out


def bm25_search(query, k, source_filter=None):
    store = _load_bm25()
    scores = store["bm25"].get_scores(tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    out = []
    for i in ranked:
        meta = store["metas"][i]
        if source_filter and meta.get("source") not in source_filter:
            continue
        out.append({"id": store["ids"][i], "doc": store["docs"][i], "meta": meta, "bscore": scores[i]})
        if len(out) >= k:
            break
    return out


def rrf_fuse(vec, bm, k=60):
    """Reciprocal Rank Fusion of two ranked lists."""
    rank = {}
    for lst in (vec, bm):
        for r, item in enumerate(lst):
            rank.setdefault(item["id"], {"item": item, "score": 0.0})
            rank[item["id"]]["score"] += 1.0 / (k + r + 1)
    fused = sorted(rank.values(), key=lambda x: x["score"], reverse=True)
    return [f["item"] for f in fused]


def llm_rerank(query, candidates, top_n):
    """Lightweight local rerank: ask the LLM to score each candidate 0-10.
    Keeps the fused RRF order as a tiebreaker so rerank only ever helps."""
    for idx, c in enumerate(candidates):
        prompt = (f"On a scale of 0 to 10, how relevant is the passage to the question? "
                  f"Answer with ONLY a single integer 0-10, nothing else.\n\n"
                  f"Question: {query}\n\nPassage:\n{c['doc'][:700]}\n\nScore (0-10):")
        try:
            r = ollama.generate(model=GEN_MODEL, prompt=prompt,
                                options={"temperature": 0, "num_predict": 6, "stop": ["\n"]})
            m = re.search(r"\b(10|[0-9])\b", r["response"])
            c["rerank"] = int(m.group()) if m else None
        except Exception:
            c["rerank"] = None
        # fused-order tiebreaker: earlier RRF rank = small bonus, keeps stable order
        c["_fused_rank"] = idx
    # if the LLM gave usable scores, sort by them; else fall back to fused order
    if any(c.get("rerank") is not None for c in candidates):
        candidates.sort(key=lambda x: (x.get("rerank") if x.get("rerank") is not None else -1,
                                       -x["_fused_rank"]), reverse=True)
    return candidates[:top_n]


def hybrid_retrieve(query, top_k=5, pool=12, source_filter=None, rerank=True):
    """Main entry: vector + BM25 -> RRF -> (optional) LLM rerank -> top_k."""
    vec = vector_search(query, pool, source_filter)
    bm = bm25_search(query, pool, source_filter)
    fused = rrf_fuse(vec, bm)[:pool]
    if rerank and fused:
        fused = llm_rerank(query, fused, top_k)
    else:
        fused = fused[:top_k]
    return [{"doc": f["doc"], "meta": f["meta"],
             "score": round(f.get("rerank", f.get("vscore", 0)), 3)} for f in fused]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_bm25()
    else:
        q = sys.argv[1] if len(sys.argv) > 1 else "What is T1059 and how to detect it?"
        for h in hybrid_retrieve(q, source_filter=None):
            print(f"[{h['score']}] {h['meta'].get('doc')} ({h['meta'].get('source')})")
