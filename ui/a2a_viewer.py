# ui/a2a_viewer.py

from __future__ import annotations
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

GREEN_URL = os.getenv("GREEN_URL", "http://localhost:9101")

app = FastAPI(title="CRM Arena Pro — A2A Viewer", version="0.1")

HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>CRM Arena Pro — A2A Viewer</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
  <div class="max-w-6xl mx-auto p-6 space-y-6">
    <header class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">CRM Arena Pro — A2A Viewer</h1>
      <span class="text-xs text-slate-500">Green URL: <code id="green-url"></code></span>
    </header>
    <section class="bg-white rounded-xl shadow-sm border p-4 space-y-4">
      <h2 class="font-semibold">Task Controls</h2>
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
        <div>
          <label class="block text-sm text-slate-600 mb-1">Persona</label>
          <select id="persona" class="w-full border rounded-lg p-2">
            <option>ServiceAgent</option>
            <option>Analyst</option>
            <option>Manager</option>
          </select>
        </div>
        <div>
          <label class="block text-sm text-slate-600 mb-1">Difficulty</label>
          <select id="difficulty" class="w-full border rounded-lg p-2">
            <option>easy</option>
            <option>medium</option>
            <option>hard</option>
          </select>
        </div>
        <div class="flex gap-2">
          <button id="btn-start" class="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">Start Session</button>
          <button id="btn-continue" class="px-4 py-2 rounded-lg bg-slate-200 hover:bg-slate-300" disabled>Continue</button>
        </div>
        <div>
          <label class="block text-sm text-slate-600 mb-1">Session ID</label>
          <input id="session-id" class="w-full border rounded-lg p-2 bg-slate-100" readonly placeholder="— no session —"/>
        </div>
      </div>
    </section>
    <section class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="bg-white rounded-xl shadow-sm border p-4 space-y-3">
        <h2 class="font-semibold">Latest Result</h2>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="text-xs text-slate-500 mb-1">Validation</div>
            <pre id="validation" class="text-sm bg-slate-50 border rounded-md p-2 overflow-auto h-40">—</pre>
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">Scores</div>
            <pre id="scores" class="text-sm bg-slate-50 border rounded-md p-2 overflow-auto h-40">—</pre>
          </div>
        </div>
        <div>
          <div class="text-xs text-slate-500 mb-1">Raw Response</div>
          <pre id="last-response" class="text-xs bg-slate-50 border rounded-md p-2 overflow-auto h-48">—</pre>
        </div>
      </div>
      <div class="bg-white rounded-xl shadow-sm border p-4 space-y-3">
        <h2 class="font-semibold">Session Transcript</h2>
        <div class="flex gap-2">
          <button id="btn-refresh" class="px-3 py-1.5 rounded-lg bg-slate-200 hover:bg-slate-300" disabled>Refresh Transcript</button>
          <button id="btn-copy" class="px-3 py-1.5 rounded-lg bg-slate-200 hover:bg-slate-300" disabled>Copy JSON</button>
        </div>
        <pre id="transcript" class="text-xs bg-slate-50 border rounded-md p-2 overflow-auto h-[28rem]">—</pre>
      </div>
    </section>
  </div>
<script>
const GREEN_URL = "{{GREEN_URL}}";
document.getElementById("green-url").innerText = GREEN_URL;
const btnStart = document.getElementById("btn-start");
const btnContinue = document.getElementById("btn-continue");
const btnRefresh = document.getElementById("btn-refresh");
const btnCopy = document.getElementById("btn-copy");
const personaSel = document.getElementById("persona");
const diffSel = document.getElementById("difficulty");
const sessionIdEl = document.getElementById("session-id");
const lastRespEl = document.getElementById("last-response");
const transcriptEl = document.getElementById("transcript");
const validationEl = document.getElementById("validation");
const scoresEl = document.getElementById("scores");

function show(obj, el){
  try { el.textContent = JSON.stringify(obj, null, 2); }
  catch (e) { el.textContent = String(obj); }
}

async function startSession(){
  btnStart.disabled = true;
  btnContinue.disabled = true;
  btnRefresh.disabled = true;
  btnCopy.disabled = true;
  validationEl.textContent = "—";
  scoresEl.textContent = "—";
  lastRespEl.textContent = "Starting…";
  const persona = personaSel.value;
  const difficulty = diffSel.value;
  try {
    const r = await fetch(`${GREEN_URL}/a2a/start?persona=${encodeURIComponent(persona)}&difficulty=${encodeURIComponent(difficulty)}`, { method: "POST" });
    const data = await r.json();
    show(data, lastRespEl);
    const sid = data.session_id || (data.feedback && data.feedback.session_id);
    if (sid){
      sessionIdEl.value = sid;
      btnContinue.disabled = !data || data.done === true;
      btnRefresh.disabled = false;
      btnCopy.disabled = false;
    }
    if (data.validation) show(data.validation, validationEl);
    if (data.scores)     show(data.scores, scoresEl);
  } catch (e){
    lastRespEl.textContent = "Error: " + e;
  } finally {
    btnStart.disabled = false;
  }
}

async function continueSession(){
  const sid = sessionIdEl.value.trim();
  if (!sid){ alert("No session id"); return; }
  btnContinue.disabled = true;
  lastRespEl.textContent = "Continuing…";
  try {
    const r = await fetch(`/api/continue?session_id=${encodeURIComponent(sid)}`, { method: "POST" });
    const data = await r.json();
    show(data, lastRespEl);
    if (data.validation) show(data.validation, validationEl);
    if (data.scores)     show(data.scores, scoresEl);
    btnContinue.disabled = data && data.done === true;
  } catch(e){
    lastRespEl.textContent = "Error: " + e;
  }
}

async function refreshTranscript(){
  const sid = sessionIdEl.value.trim();
  if (!sid){ alert("No session id"); return; }
  transcriptEl.textContent = "Loading…";
  try {
    const r = await fetch(`/api/session/${encodeURIComponent(sid)}`);
    const data = await r.json();
    show(data, transcriptEl);
  } catch(e){
    transcriptEl.textContent = "Error: " + e;
  }
}

async function copyTranscript(){
  try {
    await navigator.clipboard.writeText(transcriptEl.textContent);
    alert("Copied transcript JSON to clipboard.");
  } catch (e) {
    alert("Copy failed: " + e);
  }
}

btnStart.addEventListener("click", startSession);
btnContinue.addEventListener("click", continueSession);
btnRefresh.addEventListener("click", refreshTranscript);
btnCopy.addEventListener("click", copyTranscript);
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home(_: Request):
    # inject GREEN_URL string
    return HTMLResponse(HTML.replace("{{GREEN_URL}}", GREEN_URL))

# These API routes proxy to the green server to avoid CORS headaches from the page.
@app.post("/api/continue")
async def api_continue(session_id: str):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{GREEN_URL}/a2a/continue", params={"session_id": session_id})
        return JSONResponse(content=r.json())

@app.get("/api/session/{session_id}")
async def api_session(session_id: str):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{GREEN_URL}/sessions/{session_id}")
        return JSONResponse(content=r.json())
