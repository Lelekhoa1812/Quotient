"""Submit one media object to the local Quotient MCP API and record a benchmark.

Usage: scripts/bench_meeting.py <object_key> <label>
Writes .local/run/bench/<label>-{submitted,result,summary,graph}.json and prints the summary.
The object must already exist under derivatives/ (the worker reads it from disk).
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8080/mcp"
ROOT = Path(__file__).resolve().parents[1]
OBJECT_KEY = sys.argv[1]
LABEL = sys.argv[2]
OUT = ROOT / ".local" / "run" / "bench"
OUT.mkdir(parents=True, exist_ok=True)
PREFIX = f"{LABEL}-"
BASE_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def post(body, headers, timeout=120):
    request = Request(BASE, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
        return response.status, json.loads(content) if content else None, dict(response.headers)


status, initialized, response_headers = post({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "quotient-bench", "version": "1"},
    },
}, BASE_HEADERS)
if status != 200:
    raise RuntimeError(f"MCP initialize failed with HTTP {status}")
session_id = response_headers.get("mcp-session-id")
protocol = response_headers.get("mcp-protocol-version", "2025-03-26")
if not session_id:
    raise RuntimeError("MCP initialize returned no session")
headers = {**BASE_HEADERS, "MCP-Session-Id": session_id, "MCP-Protocol-Version": protocol}
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)

created_at = datetime.now(timezone.utc).isoformat()
status, created, _ = post({
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {
        "name": "submit_meeting",
        "arguments": {"object_key": OBJECT_KEY, "upload_complete": True},
        "task": {"ttl": 86_400_000},
        "_meta": {"progressToken": LABEL},
    },
}, headers)
if status != 200 or "error" in created:
    raise RuntimeError(f"Meeting submission failed: HTTP {status}")
task = created["result"]["task"]
task_id = task["taskId"]
(OUT / f"{PREFIX}task-id").write_text(task_id)
(OUT / f"{PREFIX}submitted.json").write_text(json.dumps({"created_at": created_at, "task": task}, indent=2))
print(f"submitted task={task_id} status={task['status']}", flush=True)

request_id = 10
last_message = ""
started = time.monotonic()
while True:
    request_id += 1
    status, response, _ = post({
        "jsonrpc": "2.0", "id": request_id, "method": "tasks/get",
        "params": {"taskId": task_id},
    }, headers)
    if status != 200 or not response or "error" in response:
        raise RuntimeError(f"Task poll failed: HTTP {status}")
    current = response["result"]
    message = current.get("statusMessage", "")
    if message and message != last_message:
        elapsed = int(time.monotonic() - started)
        print(f"elapsed={elapsed}s task_status={current['status']} phase={message}", flush=True)
        last_message = message
    if current["status"] in {"completed", "failed", "cancelled"}:
        break
    time.sleep(10)

request_id += 1
status, result, _ = post({
    "jsonrpc": "2.0", "id": request_id, "method": "tasks/result",
    "params": {"taskId": task_id},
}, headers)
if status != 200 or not result or "error" in result:
    raise RuntimeError(f"Task result unavailable: HTTP {status}")
result_body = result["result"]
(OUT / f"{PREFIX}result.json").write_text(json.dumps(result_body, indent=2))
meeting_id = (result_body.get("structuredContent") or {}).get("meeting_id")
if not meeting_id:
    message = current.get("statusMessage", "")
    meeting_id = message.split()[1] if message.startswith("Meeting ") else None
if not meeting_id:
    raise RuntimeError("Completed task had no meeting id")

pages = []
cursor = None
request_id += 1
for page_num in range(1, 51):
    args = {"meeting_id": meeting_id}
    if cursor:
        args["cursor"] = cursor
    request_id += 1
    status, response, _ = post({
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": "read_graph", "arguments": args},
    }, headers)
    if status != 200 or not response or "error" in response:
        raise RuntimeError(f"Graph page {page_num} failed: HTTP {status}")
    tool = response["result"]
    if tool.get("isError"):
        raise RuntimeError(f"Graph page {page_num} returned an MCP tool error")
    page = tool.get("structuredContent")
    if not isinstance(page, dict):
        blocks = tool.get("content", [])
        page = json.loads(blocks[0]["text"]) if blocks else {}
    pages.append(page)
    cursor = page.get("nextCursor") or page.get("next_cursor")
    if not cursor:
        break
else:
    raise RuntimeError("Graph pagination exceeded 50 pages")

result_summary = (result_body.get("structuredContent") or {})
claim_rows = [item for page in pages for item in page.get("claims", [])]
span_rows = [item for page in pages for item in page.get("spans", [])]
gap_rows = [item for page in pages for item in page.get("gaps", [])]
review_rows = [item for item in claim_rows if item.get("status") != "supported"]
span_text = {item.get("span_id"): item.get("text", "") for item in span_rows}
citation_rows = [citation for claim in claim_rows for citation in claim.get("citations", [])]
invalid_citations = [
    citation
    for citation in citation_rows
    if citation.get("span_id") not in span_text
    or not citation.get("quote")
    or citation["quote"] not in span_text[citation["span_id"]]
]
summary = {
    "created_at": created_at,
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(time.monotonic() - started, 1),
    "task_id": task_id,
    "meeting_id": meeting_id,
    "task_status": current["status"],
    "task_status_message": current.get("statusMessage"),
    "meeting_status": result_summary.get("status"),
    "review_counts": result_summary.get("review_counts"),
    "artifacts": result_summary.get("artifacts"),
    "withheld": result_summary.get("withheld"),
    "span_count": len(span_rows),
    "claim_count": len(claim_rows),
    "supported_claim_count": sum(item.get("status") == "supported" for item in claim_rows),
    "gap_claim_count": sum(item.get("status") == "gap" for item in claim_rows),
    "review_row_count": len(review_rows),
    "gap_count": len(gap_rows),
    "gap_span_reference_count": sum(len(item.get("span_ids", [])) for item in gap_rows),
    "citation_count": len(citation_rows),
    "invalid_citation_count": len(invalid_citations),
    "finding_count": sum(len(page.get("findings", [])) for page in pages),
    "synthesis_count": sum(len(page.get("synthesis", [])) for page in pages),
    "action_count": sum(len(page.get("actions", [])) for page in pages),
    "coarse_span_count": sum(bool(item.get("coarse")) for item in span_rows),
    "speaker_attributed_span_count": sum(bool(item.get("speaker_hypothesis_id")) for item in span_rows),
    "chart_count": len(pages[0].get("charts", [])) if pages else 0,
    "dimension_count": len(pages[0].get("dimensions", [])) if pages else 0,
    "page_count": len(pages),
    "first_page_bytes": len(json.dumps(pages[0]).encode()) if pages else 0,
    "later_page_bytes": [len(json.dumps(page).encode()) for page in pages[1:]],
    "later_pages_repeat_raw_transcript": any("raw_transcript" in page for page in pages[1:]),
    "later_pages_repeat_charts": any("charts" in page for page in pages[1:]),
    "progress_message": pages[0].get("status"),
}
(OUT / f"{PREFIX}summary.json").write_text(json.dumps(summary, indent=2))
(OUT / f"{PREFIX}graph.json").write_text(json.dumps(pages))
print(json.dumps(summary, indent=2), flush=True)
