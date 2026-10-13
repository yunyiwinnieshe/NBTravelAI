"""Local AI-call dashboard data. Enable explicitly; keep off public deployments."""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from travel_ai.services.ai_tracing import recent_calls

router = APIRouter(tags=["observability"])


@router.get("/observability/ai-calls")
def ai_calls() -> dict:
    if os.getenv("ENABLE_LOCAL_AI_DASHBOARD") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    calls = recent_calls()
    return {
        "calls": calls,
        "total": len(calls),
        "failures": sum(call["status"] != "ok" for call in calls),
    }


@router.get("/observability/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    if os.getenv("ENABLE_LOCAL_AI_DASHBOARD") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    return """<!doctype html><html><head><meta charset='utf-8'><title>AI calls</title>
<style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%}
th,td{padding:.5rem;border-bottom:1px solid #ddd;text-align:left}
.error{color:#b00020}</style></head><body><h1>AI calls</h1>
<p>Process-local, last 500 calls. Inputs and outputs are fingerprints,
not message text.</p>
<p id='summary'></p><table><thead><tr><th>Time</th><th>Operation</th><th>Status</th>
<th>Latency (ms)</th><th>Tokens in/out</th>
<th>Input / output fingerprint</th></tr></thead>
<tbody id='rows'></tbody></table><script>
async function refresh(){
const data=await(await fetch('/observability/ai-calls')).json();
document.getElementById('summary').textContent=
`${data.total} calls · ${data.failures} failures`;
const rows=document.getElementById('rows');rows.replaceChildren();
for(const c of data.calls){const tr=document.createElement('tr');
for(const value of [c.at,c.operation,c.status,c.latency_ms,
`${c.prompt_tokens??'–'} / ${c.completion_tokens??'–'}`,
`${c.input_fingerprint} / ${c.output_fingerprint??'–'}`]){
const td=document.createElement('td');td.textContent=value;tr.appendChild(td)}
if(c.status!=='ok')tr.className='error';rows.appendChild(tr)}}
refresh();setInterval(refresh,5000)</script></body></html>"""
