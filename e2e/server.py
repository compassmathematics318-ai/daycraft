"""QA-only server with a token-guarded clean shutdown endpoint."""
import sys
from pathlib import Path
import os
import importlib

import uvicorn
from fastapi import Request, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

app = importlib.import_module("backend.app.main").create_app()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8876))


@app.post("/__qa_shutdown")
async def shutdown(request: Request):
    if request.headers.get("x-qa-token") != os.environ.get("SCHEDULE_QA_TOKEN"):
        raise HTTPException(403, "Invalid QA shutdown token")
    server.should_exit = True
    return {"stopping": True}


server.run()
