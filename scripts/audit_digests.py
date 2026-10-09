"""Motivation vs Logic
Motivation: A repeatable check, with no model calls, that what the portal shows still rests on the recording:
every walkaway item cites lines that exist, every key figure matches its cited line, every answered question
is answered after it was asked. It does not measure completeness or usefulness; only a scored run can.
Logic: Reads .local/run/meetings.json, projects each meeting through the API gate (so it audits what a
client would receive), and counts the three checks per meeting. Run from the repo root with the worker venv:
  /tmp/quotient-worker-venv/bin/python scripts/audit_digests.py
"""
import json, re, sys
sys.path.insert(0, "apps/api"); sys.path.insert(0, "apps/worker")
from graph.numbers import grounded
from quotient.graph.gate import project_meeting
rows = json.load(open(".local/run/meetings.json"))["meetings"]
rows = rows.values() if isinstance(rows, dict) else rows
norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
nums = lambda t: set(x.rstrip(".") for x in re.findall(r"\d+(?:\.\d+)?", (t or "").replace(",", "")))
tot = {"items": 0, "cited": 0, "bad_cite": 0, "figs": 0, "fig_ok": 0, "quotes": 0, "quote_ok": 0, "qs": 0, "q_order_ok": 0, "basis": {}}
print(f"{'meeting':44} items  cited  figs(ok)  quotes(ok)  q-order  basis")
for row in rows:
    if not isinstance(row, dict): continue
    g = project_meeting(row)["graph"]; d = g.get("digest")
    if not d: continue
    spans = {s["span_id"]: s for s in g["spans"]}
    rawtext = lambda ids: " ".join((spans[i].get("text") or spans[i].get("raw_text") or "") for i in ids if i in spans)
    text = lambda ids: " ".join(norm(spans[i].get("text") or spans[i].get("raw_text")) for i in ids if i in spans)
    c = {"items": 0, "cited": 0, "figs": 0, "fig_ok": 0, "quotes": 0, "quote_ok": 0, "qs": 0, "q_ok": 0}
    basis = {}
    for key in ("decisions", "actions", "open_questions", "disagreements", "key_figures", "risks", "concepts", "perspectives", "summary"):
        for it in d.get(key) or []:
            c["items"] += 1
            ids = list(it.get("span_ids") or []) + [it.get(k) for k in ("span_id", "asked_span_id") if it.get(k)]
            for p in it.get("positions") or []: ids += p.get("span_ids") or []
            if ids and all(i in spans for i in ids): c["cited"] += 1
            b = it.get("basis"); basis[b] = basis.get(b, 0) + 1
            if key == "key_figures":
                c["figs"] += 1
                if any(grounded(str(it.get("value")), spans[i].get("text") or spans[i].get("raw_text") or "") for i in ids if i in spans): c["fig_ok"] += 1
            if key == "actions" and it.get("quote"):
                c["quotes"] += 1
                if norm(it["quote"]) in text(ids): c["quote_ok"] += 1
            if key == "open_questions" and it.get("answered") and it.get("answer_ms") is not None:
                c["qs"] += 1
                if it["answer_ms"] >= (it.get("start_ms") or 0): c["q_ok"] += 1
    print(f"{(d.get('title') or '')[:42]:44} {c['items']:5}  {c['cited']:5}  {c['fig_ok']}/{c['figs']}      {c['quote_ok']}/{c['quotes']}       {c['q_ok']}/{c['qs']}     {basis}")
    for k in ("items","cited","figs","fig_ok","quotes","quote_ok","qs"): tot[k] += c[k]
    tot["q_order_ok"] += c["q_ok"]
print("TOTAL", {k: v for k, v in tot.items() if k != "basis"})
