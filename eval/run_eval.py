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
import ollama
from rag.engine import answer
from rag.hybrid import hybrid_retrieve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS_PATH = os.path.join(ROOT, "eval", "questions.json")
JUDGE_LOCAL = "qwen2.5-coder:7b-64k"  # fallback judge if no cloud


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


def judge(question, ans, judge_model):
    """LLM-judge: score answer correctness 0-1 for a cybersecurity question."""
    prompt = (f"You are grading a cybersecurity answer. Question: {question}\n\n"
              f"Answer: {ans[:1500]}\n\n"
              "Score the answer's technical correctness and completeness from 0 to 10 "
              "(10=fully correct and complete, 0=wrong/empty). Reply ONLY the number.")
    try:
        r = ollama.generate(model=judge_model, prompt=prompt,
                            options={"temperature": 0, "num_predict": 4})
        import re
        m = re.search(r"\d+", r["response"])
        return round(int(m.group()) / 10, 3) if m else None
    except Exception:
        return None


def cloud_answer(question):
    """Cloud ceiling via Hermes `hermes send`-style — here we shell to the default profile.
    Returns (answer, latency). Requires portal creds in the default profile."""
    import subprocess
    t0 = time.time()
    try:
        p = subprocess.run(
            ["hermes", "-z", f"Answer as a cybersecurity analyst, concise and technical: {question}"],
            capture_output=True, text=True, timeout=180)
        return p.stdout.strip(), round(time.time() - t0, 1)
    except Exception as e:
        return f"[cloud error: {e}]", round(time.time() - t0, 1)


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

    judge_model = JUDGE_LOCAL  # local self-judge by default (still informative)

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
            row["local_only"]["judge"] = judge(q["question"], row["local_only"]["answer"], judge_model)
            row["cyberrag"]["judge"] = judge(q["question"], row["cyberrag"]["answer"], judge_model)
            if args.cloud:
                row["cloud"]["judge"] = judge(q["question"], row["cloud"]["answer"], judge_model)
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
