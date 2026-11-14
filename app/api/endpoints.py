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
def spherexpng(
    ra_deg: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
    dec_deg: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    cutout_size_i: float = Query(0.05, gt=0, le=1, allow_inf_nan=False),
    fake_color_theme: str = Query("gray", max_length=64),
):
    # Implement the logic to return the PNG image here
    return Response(content=b"PNG_DATA", media_type="image/png")

@router.get(
    "/hello",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}},
)
def hello(number: float):
    return Response(content=f"Hello, World! {number}", media_type="text/plain")