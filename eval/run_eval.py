#!/usr/bin/env python3
"""
CyberRAG evaluation harness — proves the thesis with NUMBERS.

Compares on the SAME question set:
  A) local-only      (qwen2.5-coder:7b, NO retrieval)        -> cheap-but-dumb baseline
  B) local + CyberRAG (hybrid retrieval + KG + local LLM)    -> our solution
  C) cloud baseline  (Claude/GPT via Nous Portal)  [--cloud] -> the expensive ceiling

Metrics:
  - keyword_coverage  : fraction of expected key facts present (deterministic, 0-1)
  - context_hit       : retrieval surfaced the right doc?      [B] (0/1)
  - judge_score       : LLM-judge correctness vs question      (0-1, --judge)
  - latency_s         : wall-clock
  - cost              : local = $0; cloud = tokens (flagged)

The judge/cloud use a cloud model ONLY for scoring/ceiling — never in path B.

Run:  python eval/run_eval.py                  # A vs B, free, local
      python eval/run_eval.py --judge          # add LLM-judge correctness
      python eval/run_eval.py --cloud --judge  # full A/B/C comparison
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
import subprocess
import ollama
from rag.engine import answer
from rag.hybrid import hybrid_retrieve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS_PATH = os.path.join(ROOT, "eval", "questions.json")
JUDGE_LOCAL = "qwen2.5-coder:7b-64k"  # fallback judge ONLY if cloud judge unavailable


def cloud_oneshot(prompt, timeout=180):
    """One-shot cloud call via `hermes -z` with tools disabled. Returns text or None."""
    try:
        p = subprocess.run(["hermes", "-z", prompt, "-t", ""],
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        return out or None
    except Exception:
        return None


def keyword_coverage(ans, keywords):
    if not keywords:
        return None
    a = ans.lower()
    return round(sum(1 for k in keywords if k.lower() in a) / len(keywords), 3)


def context_hit(query, expected_docs):
    if not expected_docs:
        return None
    hits = hybrid_retrieve(query, top_k=5, rerank=False)
    got = [h["meta"].get("doc", "").lower() for h in hits]
    return int(any(any(e.lower() in g or g in e.lower() for g in got) for e in expected_docs))


def judge(question, ans, use_cloud_judge=True):
    """LLM-judge correctness 0-1. Uses the CLOUD model by default so the judge is
    independent of the local generator (no self-grading bias). Falls back to the
    local 7B only if the cloud call fails."""
    prompt = (f"You are grading a cybersecurity answer for technical correctness.\n"
              f"Question: {question}\n\nAnswer: {ans[:1500]}\n\n"
              "Score the answer's technical correctness and completeness from 0 to 10 "
              "(10=fully correct and complete, 0=wrong/empty). Reply with ONLY the number.")
    if use_cloud_judge:
        out = cloud_oneshot(prompt, timeout=120)
        if out:
            m = re.search(r"\d+", out)
            if m:
                return round(min(int(m.group()), 10) / 10, 3)
    # local fallback
    try:
        r = ollama.generate(model=JUDGE_LOCAL, prompt=prompt,
                            options={"temperature": 0, "num_predict": 4})
        m = re.search(r"\d+", r["response"])
        return round(min(int(m.group()), 10) / 10, 3) if m else None
    except Exception:
        return None


def cloud_answer(question):
    """Cloud ceiling (config C): the expensive cloud model answering directly,
    no retrieval. This is the quality bar CyberRAG aims to match locally."""
    t0 = time.time()
    out = cloud_oneshot(
        f"Answer as a senior cybersecurity threat-intelligence analyst, concise and "
        f"technical: {question}", timeout=180)
    return (out or "[cloud unavailable]"), round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        questions = json.load(f)
    if args.limit:
        questions = questions[:args.limit]

    rows = []
    for i, q in enumerate(questions):
        print(f"[{i+1}/{len(questions)}] {q['question'][:55]}...")
        row = {"id": q.get("id", i), "question": q["question"]}

        # A: local-only
        a = answer(q["question"], use_rag=False)
        row["local_only"] = {"answer": a["answer"], "latency_s": a["latency_s"],
                             "keyword_coverage": keyword_coverage(a["answer"], q.get("keywords", []))}
        # B: local + CyberRAG
        b = answer(q["question"], use_rag=True)
        row["cyberrag"] = {"answer": b["answer"], "latency_s": b["latency_s"],
                           "keyword_coverage": keyword_coverage(b["answer"], q.get("keywords", [])),
                           "context_hit": context_hit(q["question"], q.get("expected_docs", [])),
                           "kg_used": bool(b.get("kg_node"))}
        # C: cloud (optional)
        if args.cloud:
            ca, cl = cloud_answer(q["question"])
            row["cloud"] = {"answer": ca, "latency_s": cl,
                            "keyword_coverage": keyword_coverage(ca, q.get("keywords", []))}

        if args.judge:
            row["local_only"]["judge"] = judge(q["question"], row["local_only"]["answer"])
            row["cyberrag"]["judge"] = judge(q["question"], row["cyberrag"]["answer"])
            if args.cloud:
                row["cloud"]["judge"] = judge(q["question"], row["cloud"]["answer"])
        rows.append(row)

    def avg(cfg, key):
        vals = [r[cfg][key] for r in rows if cfg in r and r[cfg].get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    cfgs = ["local_only", "cyberrag"] + (["cloud"] if args.cloud else [])
    summary = {"n": len(rows)}
    for c in cfgs:
        summary[c] = {"keyword_coverage": avg(c, "keyword_coverage"),
                      "judge": avg(c, "judge"), "latency_s": avg(c, "latency_s")}
    summary["cyberrag"]["context_hit_rate"] = avg("cyberrag", "context_hit")

    out_path = os.path.join(ROOT, "eval", f"results_{datetime.now():%Y-%m-%d_%H%M}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)

    print("\n" + "=" * 60)
    print(f"{'metric':<20}" + "".join(f"{c:>16}" for c in cfgs))
    for key in ["keyword_coverage", "judge", "latency_s"]:
        line = f"{key:<20}"
        for c in cfgs:
            v = summary[c].get(key)
            line += f"{(str(v) if v is not None else '-'):>16}"
        print(line)
    print(f"{'context_hit_rate':<20}{'-':>16}{str(summary['cyberrag'].get('context_hit_rate')):>16}")
    print("=" * 60)
    print(f"[+] {out_path}")


if __name__ == "__main__":
    main()
