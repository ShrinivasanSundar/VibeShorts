"""FastAPI server for VibeShorts Studio."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from vibeshorts.config import VibeShortsConfig
from vibeshorts.integrations.antigravity import ShowrunnerAgent
from vibeshorts.models.timeline import Timeline


def create_app(config: VibeShortsConfig, project_dir: Path) -> FastAPI:
    app = FastAPI(title="VibeShorts Studio", version="0.1.0")
    timeline_path = project_dir / "timeline.json"
    showrunner = ShowrunnerAgent(config, project_dir)

    @app.get("/")
    def index() -> HTMLResponse:
        return HTMLResponse(_studio_html())

    @app.get("/api/timeline")
    def get_timeline():
        if timeline_path.exists():
            return json.loads(timeline_path.read_text())
        return Timeline.default_short_form().model_dump()

    @app.put("/api/timeline")
    def put_timeline(data: dict):
        timeline = Timeline.model_validate(data)
        timeline.save(timeline_path)
        return {"status": "saved", "duration": timeline.duration}

    @app.websocket("/ws/agent")
    async def agent_ws(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                message = data.get("message", "")
                response = await showrunner.chat(message)
                await websocket.send_json({"role": "assistant", "content": response})
        except WebSocketDisconnect:
            pass

    return app


def _studio_html() -> str:
    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>VibeShorts Studio</title>
  <style>
    * { box-sizing: border-box; margin: 0; }
    body { font-family: system-ui, sans-serif; background: #0f0f12; color: #e8e8ec; height: 100vh; display: flex; flex-direction: column; }
    header { padding: 12px 20px; border-bottom: 1px solid #2a2a32; font-weight: 600; }
    main { flex: 1; display: grid; grid-template-columns: 1fr 320px; gap: 0; }
    #preview { background: #000; display: flex; align-items: center; justify-content: center; }
    #timeline { border-top: 1px solid #2a2a32; padding: 16px; min-height: 120px; }
    #chat { border-left: 1px solid #2a2a32; display: flex; flex-direction: column; }
    #messages { flex: 1; overflow-y: auto; padding: 12px; font-size: 14px; }
    #input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #2a2a32; }
    input, button { background: #1a1a22; border: 1px solid #3a3a48; color: #e8e8ec; padding: 8px 12px; border-radius: 6px; }
    input { flex: 1; }
    button { cursor: pointer; }
    .track { background: #1a1a22; border-radius: 4px; padding: 8px; margin: 4px 0; font-size: 12px; }
  </style>
</head>
<body>
  <header>VibeShorts Studio</header>
  <main>
    <div>
      <div id="preview"><span style="color:#666">Preview canvas (Hyperframes)</span></div>
      <div id="timeline"><div id="tracks"></div></div>
    </div>
    <div id="chat">
      <div id="messages"></div>
      <div id="input-row">
        <input id="msg" placeholder="Talk to the showrunner agent..." />
        <button onclick="send()">Send</button>
      </div>
    </div>
  </main>
  <script>
    const ws = new WebSocket(`ws://${location.host}/ws/agent`);
    const messages = document.getElementById('messages');
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      messages.innerHTML += `<div><b>Agent:</b> ${data.content}</div>`;
    };
    function send() {
      const input = document.getElementById('msg');
      const text = input.value.trim();
      if (!text) return;
      messages.innerHTML += `<div><b>You:</b> ${text}</div>`;
      ws.send(JSON.stringify({ message: text }));
      input.value = '';
    }
    fetch('/api/timeline').then(r => r.json()).then(t => {
      document.getElementById('tracks').innerHTML = t.tracks.map(tr =>
        `<div class="track"><b>${tr.id}</b> (${tr.type}) — ${tr.items.length} clips</div>`
      ).join('');
    });
  </script>
</body>
</html>
"""
