from fastapi import FastAPI

from app.api.endpoints import router
from app.ui import register_ui

app = FastAPI()
app.include_router(router)
register_ui(app)