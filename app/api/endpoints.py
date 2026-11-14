from pathlib import Path
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

router = APIRouter()

@router.get(
    "/spherexpng",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def spherexpng():
    # Implement the logic to return the PNG image here
    return Response(content=b"PNG_DATA", media_type="image/png")

@router.get(
    "/hello",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}},
)
def hello():
    return Response(content="Hello, World!", media_type="text/plain")