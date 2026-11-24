"""Local AI-call dashboard data. Enable explicitly; keep off public deployments."""

import os
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from travel_ai.services.ai_tracing import get_trace, recent_calls, recent_traces

_basic = HTTPBasic(auto_error=False)


def _require_local_dashboard(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
) -> None:
    password = os.getenv("LOCAL_AI_DASHBOARD_PASSWORD")
    if os.getenv("ENABLE_LOCAL_AI_DASHBOARD") != "1" or not password:
        raise HTTPException(status_code=404, detail="Not found")
    if (
        credentials is None
        or not compare_digest(credentials.username, "local")
        or not compare_digest(credentials.password, password)
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )


router = APIRouter(
    tags=["observability"], dependencies=[Depends(_require_local_dashboard)]
)


@router.get("/observability/traces")
def traces() -> dict:
    return {"traces": recent_traces()}


@router.get("/observability/traces/{trace_id}")
def trace(trace_id: str) -> dict:
    result = get_trace(trace_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return result


@router.get("/observability/ai-calls")
def ai_calls() -> dict:
    calls = recent_calls()
    return {
        "calls": calls,
        "total": len(calls),
        "failures": sum(call["status"] != "ok" for call in calls),
    }


@router.get("/observability/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'>
<title>Request traces</title>
<style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%}
th,td{padding:.5rem;border-bottom:1px solid #ddd;text-align:left}
.error{color:#b00020}</style></head><body><h1>Request traces</h1>
<p>Copy the X-Trace-ID response header and open /observability/traces/&lt;id&gt;
to inspect every stage of one request. Recent requests appear below.</p>
<table><thead><tr><th>Time</th><th>Trace ID</th><th>Stages</th>
<th>Outcome</th></tr></thead>
<tbody id='traces'></tbody></table><h2>Provider calls</h2>
<p>A provider call can succeed while later extraction validation fails.
Open its request trace for the full outcome. Inputs and outputs are
fingerprints, not message text.</p>
<p id='summary'></p><table><thead><tr><th>Time</th><th>Operation</th><th>Status</th>
<th>Latency (ms)</th><th>Tokens in/out</th>
<th>Input / output fingerprint</th></tr></thead>
<tbody id='rows'></tbody></table><script>
async function refresh(){
const recent=await(await fetch('/observability/traces')).json();
const traceRows=document.getElementById('traces');traceRows.replaceChildren();
for(const trace of recent.traces.slice(0,20)){
const tr=document.createElement('tr');
const last=trace.stages.at(-1);
const values=[trace.at,trace.trace_id,
trace.stages.map(s=>s.stage).join(' → '),
last?.http_status??last?.status??'–'];
for(let i=0;i<values.length;i++){
const td=document.createElement('td');
if(i===1){const a=document.createElement('a');
a.href='/observability/traces/'+encodeURIComponent(trace.trace_id);
a.textContent=values[i];td.appendChild(a)}else{td.textContent=values[i]}
tr.appendChild(td)}traceRows.appendChild(tr)}
const data=await(await fetch('/observability/ai-calls')).json();
document.getElementById('summary').textContent=
`${data.total} calls · ${data.failures} provider failures`;
const rows=document.getElementById('rows');rows.replaceChildren();
for(const c of data.calls){const tr=document.createElement('tr');
for(const value of [c.at,c.operation,c.status,c.latency_ms,
`${c.prompt_tokens??'–'} / ${c.completion_tokens??'–'}`,
`${c.input_fingerprint} / ${c.output_fingerprint??'–'}`]){
const td=document.createElement('td');td.textContent=value;tr.appendChild(td)}
if(c.status!=='ok')tr.className='error';rows.appendChild(tr)}}
refresh();setInterval(refresh,5000)</script></body></html>"""
