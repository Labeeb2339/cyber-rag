#!/usr/bin/env python3
"""
CyberRAG ingest — load the security corpus, chunk, embed locally, store in Chroma.

All local: embeddings via Ollama (nomic-embed-text), vector store ChromaDB on disk.
No network egress. Run:  python ingest/build_index.py
"""
import os
import re
import sys
import glob
import hashlib
import json

import chromadb
import ollama
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(ROOT, "data", "chroma")
COLLECTION = "cyber_kb"
EMBED_MODEL = "nomic-embed-text"

# Corpus sources on this machine.
CORPUS_GLOBS = [
    (r"C:/Users/Labeeb/cyber-arsenal/skill-libs/Anthropic-Cybersecurity-Skills/skills/*/SKILL.md", "anthropic-cyber"),
    (r"C:/Users/Labeeb/cyber-arsenal/skill-libs/Claude-BugHunter/skills/*/SKILL.md", "bughunter"),
    (r"C:/Users/Labeeb/obsidian-vault/Cybersecurity/*.md", "vault-notes"),
    # Authoritative corpora (fetched by fetch_authoritative.py)
    (os.path.join(ROOT, "corpus", "attack", "*.md"), "mitre-attack"),
    (os.path.join(ROOT, "corpus", "kev", "*.md"), "cisa-kev"),
    (os.path.join(ROOT, "corpus", "capec", "*.md"), "capec"),
    (os.path.join(ROOT, "corpus", "sigma", "*.md"), "sigma"),
]

ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")  # MITRE technique IDs


def embed(texts):
    """Embed a list of strings locally via Ollama."""
    out = []
    for t in texts:
        r = ollama.embeddings(model=EMBED_MODEL, prompt=t)
        out.append(r["embedding"])
    return out


def extract_meta(path, source, text):
    name = os.path.basename(os.path.dirname(path)) if path.endswith("SKILL.md") else os.path.basename(path)
    attack_ids = sorted(set(ATTACK_RE.findall(text)))
    return {
        "source": source,
        "doc": name,
        "path": path,
        "attack_ids": ",".join(attack_ids[:10]),
    }


def main():
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1800, chunk_overlap=200,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
    )

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    # fresh build
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    files = []
    for pattern, source in CORPUS_GLOBS:
        for p in glob.glob(pattern):
            files.append((p, source))
    print(f"[ingest] {len(files)} source documents")

    batch_ids, batch_docs, batch_meta = [], [], []
    n_chunks = 0
    for i, (path, source) in enumerate(files):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"  skip {path}: {e}")
            continue
        if not text.strip():
            continue
        meta = extract_meta(path, source, text)
        for j, chunk in enumerate(splitter.split_text(text)):
            cid = hashlib.md5(f"{path}:{j}".encode()).hexdigest()
            batch_ids.append(cid)
            batch_docs.append(chunk)
            batch_meta.append({**meta, "chunk": j})
            n_chunks += 1
        # flush every ~64 docs to keep memory low
        if len(batch_docs) >= 128:
            col.add(ids=batch_ids, embeddings=embed(batch_docs),
                    documents=batch_docs, metadatas=batch_meta)
            print(f"  [{i+1}/{len(files)}] indexed, {n_chunks} chunks so far")
            batch_ids, batch_docs, batch_meta = [], [], []

    if batch_docs:
        col.add(ids=batch_ids, embeddings=embed(batch_docs),
                documents=batch_docs, metadatas=batch_meta)

    print(f"[ingest] DONE — {n_chunks} chunks from {len(files)} docs")
    print(f"[ingest] collection count: {col.count()}")
    # save a small manifest
    with open(os.path.join(ROOT, "data", "manifest.json"), "w") as f:
        json.dump({"docs": len(files), "chunks": n_chunks,
                   "embed_model": EMBED_MODEL, "collection": COLLECTION}, f, indent=2)


if __name__ == "__main__":
    main()
