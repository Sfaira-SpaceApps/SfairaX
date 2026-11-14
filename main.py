from fastapi import FastAPI
import logging
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from nicegui import run

from app.api.endpoints import router
from app.ui import register_ui


if os.environ.get("VERCEL") == "1":
    # NiceGUI 4 initializes an optional CPU worker pool at startup. Vercel
    # lacks the OS semaphores required by multiprocessing; this app does not
    # use run.cpu_bound. Keep normal pool initialization outside Vercel.
    def setup_without_process_pool() -> None:
        logging.getLogger(__name__).info(
            "Skipping NiceGUI CPU process pool on Vercel; run.cpu_bound is unavailable."
        )

    run.setup = setup_without_process_pool


app = FastAPI()
app.include_router(router)
assets = Path(__file__).resolve().parent / "www"/ "assets"
app.mount("/assets", StaticFiles(directory=assets), name="assets")
register_ui(app)
