from fastapi import FastAPI
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from app.api.endpoints import router
from app.ui import register_ui


app = FastAPI()
app.include_router(router)
assets = Path(__file__).resolve().parent / "www"/ "assets"
app.mount("/assets", StaticFiles(directory=assets), name="assets")
register_ui(app)
