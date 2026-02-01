from fastapi import FastAPI, Request, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler

from config import load_config, save_config, AppConfig
from emby_client import EmbyClient
from task_manager import task_manager, manager

# Logging setup
os.makedirs("data", exist_ok=True)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler = RotatingFileHandler("data/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

# Root/app logger
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
logger = logging.getLogger("app")

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(title="Emby Strm Doctor")

# Create templates directory if not exists (handled by mkdir)
templates = Jinja2Templates(directory="templates")

class LibraryRequest(BaseModel):
    library_id: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/config", response_model=AppConfig)
async def get_config():
    return load_config()

@app.post("/api/config")
async def update_config(config: AppConfig):
    save_config(config)
    return {"status": "success", "message": "Configuration saved"}

@app.get("/api/libraries")
async def get_libraries():
    config = load_config()
    if not config.emby_host or not config.api_key or not config.user_id:
        raise HTTPException(status_code=400, detail="Emby configuration missing")
    
    client = EmbyClient(config.emby_host, config.api_key, config.user_id)
    try:
        libraries = await client.get_libraries()
        return libraries
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    return {
        "is_running": task_manager.is_running,
        "current_library_id": getattr(task_manager, "current_library_id", None),
        "statistics": getattr(task_manager, "stats", {"total": 0, "processed": 0, "success": 0}),
    }

@app.post("/api/start")
async def start_task(req: LibraryRequest):
    success, msg = await task_manager.start_task(req.library_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.post("/api/stop")
async def stop_task():
    success, msg = await task_manager.stop_task()
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, maybe wait for commands if needed
            # For now we just push logs from task_manager
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
