from pathlib import Path
from datetime import date
from urllib.parse import urlencode

from astropy.time import Time

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from app.services import spherex_service

router = APIRouter()

@router.get(
    "/spherexpng",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def spherexpng(
    ra_deg: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
    dec_deg: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    cutout_size_i: float = Query(180.0, gt=0, le=3600, allow_inf_nan=False, description="Cutout size in arcseconds."),
    fake_color_theme: str = Query("gray", max_length=64),
) -> Response:
     # Implement the logic to return the PNG image here
    try:
        png = spherex_service.query_spherex(ra_deg, dec_deg, cutout_size_i, fake_color_theme)

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except spherex_service.SpherexNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except spherex_service.SpherexUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")

def _spherex_error(exc):
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, spherex_service.SpherexNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, spherex_service.SpherexUpstreamError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))

@router.get("/spherex/observations")
def get_spherex_observations(
    ra_deg: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
    dec_deg: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    cutout_size_i: float = Query(180.0, gt=0, le=3600, allow_inf_nan=False, description="Cutout size in arcseconds."),
    fake_color_theme: str = Query("gray", max_length=64),
    time_start: date = Query(...),
    time_end: date = Query(...),
):
    try:
        if time_start > time_end:
            raise ValueError("Start date must precede end date.")
        if fake_color_theme not in spherex_service.matplotlib.colormaps:
            raise ValueError("Unknown color theme.")
        end_mjd = spherex_service.date_to_mjd(time_end) + 1
        rows = spherex_service.find_spherex_observations(
            ra_deg, dec_deg, cutout_size_i, time_start, end_mjd
        )
        frames = []
        counts = {}
        is_example = rows.meta.get("source") == "example"
        for row in rows:
            mjd = float(row["time_bounds_lower"])
            if not is_example and mjd >= end_mjd:
                continue
            bandpass = str(row["energy_bandpassname"])
            key = (mjd, bandpass)
            index = counts.get(key, 0)
            counts[key] = index + 1
            params = urlencode(dict(ra_deg=ra_deg, dec_deg=dec_deg,
                cutout_size_i=cutout_size_i, fake_color_theme=fake_color_theme,
                mjd=mjd, bandpass=bandpass, artifact_index=index,
                artifact_uri=str(row["artifact_uri"])))
            frame = dict(mjd=mjd, date=Time(mjd, format="mjd").isot + "Z",
                bandpass=bandpass, image_url="/spherex/frame?" + params)
            if is_example:
                example = spherex_service.example_frame(str(row["artifact_uri"]))
                frame.update({key: example[key] for key in ("ra_deg", "dec_deg", "source_url")})
            frames.append(frame)
        if not frames:
            raise spherex_service.SpherexNotFoundError("No observations in this date range.")
        return {"bandpasses": sorted({f["bandpass"] for f in frames}), "frames": frames,
                "source": "example" if is_example else "irsa",
                "message": spherex_service.EXAMPLE_MESSAGE if is_example else None}
    except (ValueError, spherex_service.SpherexNotFoundError, spherex_service.SpherexUpstreamError) as exc:
        raise _spherex_error(exc) from exc

@router.get("/spherex/frame", response_class=Response)
def get_spherex_frame(
    ra_deg: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
    dec_deg: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    mjd: float = Query(..., allow_inf_nan=False),
    bandpass: str = Query(..., min_length=1, max_length=128),
    artifact_index: int = Query(0, ge=0),
    artifact_uri: str | None = Query(None, min_length=1, max_length=2048),
    cutout_size_i: float = Query(180.0, gt=0, le=3600, allow_inf_nan=False, description="Cutout size in arcseconds."),
    fake_color_theme: str = Query("gray", max_length=64),
    vmin: float | None = Query(None, allow_inf_nan=False),
    vmax: float | None = Query(None, allow_inf_nan=False),
):
    """Download a validated artifact directly, avoiding another catalog query."""
    try:
        if artifact_uri is not None and artifact_uri.startswith("example:"):
            spherex_service.example_frame(artifact_uri)  # Resolve only known bundled IDs.
            fits_url = artifact_uri
        elif artifact_uri is not None:
            fits_url = spherex_service.spherex_cutout_url(
                artifact_uri, ra_deg, dec_deg, cutout_size_i
            )
        else:
            # Compatibility with frame links generated before artifact IDs.
            tolerance = 1e-3
            rows = spherex_service.find_spherex_observations(
                ra_deg, dec_deg, cutout_size_i, mjd - tolerance, mjd + tolerance, bandpass
            )
            # Compare the serialized values after the broader catalog lookup.
            if rows.meta.get("source") != "example":
                rows = rows[abs(rows["time_bounds_lower"] - mjd) < 1e-7]
            if artifact_index >= len(rows):
                raise spherex_service.SpherexNotFoundError("Observation no longer available.")
            fits_url = str(rows["download_url"][artifact_index])
        png, lower, upper, example = spherex_service.render_available_frame(
            fits_url, fake_color_theme, vmin, vmax
        )
        return Response(png, media_type="image/png", headers={
            "X-Image-Vmin": str(lower), "X-Image-Vmax": str(upper),
            "X-SPHEREx-Source": "example" if example else "irsa",
            **({"X-SPHEREx-Example-ID": example["id"]} if example else {}),
        })
    except (ValueError, spherex_service.SpherexNotFoundError, spherex_service.SpherexUpstreamError) as exc:
        raise _spherex_error(exc) from exc

@router.get(
    "/hello",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}},
)
def hello(number: float):
    return Response(content=f"Hello, World! {number}", media_type="text/plain")

@router.get("/images") #this was to test while the image playback was being developed
def images():
    return {
        "frames": [
            {"date": "2025-01-01", "src": "/assets/images/mock/mock_one.png"},
            {"date": "2025-01-02", "src": "/assets/images/mock/mock_two.png"},
            {"date": "2025-01-03", "src": "/assets/images/mock/mock_three.png"},
            {"date": "2025-01-04", "src": "/assets/images/mock/mock_four.png"},
            {"date": "2025-01-05", "src": "/assets/images/mock/mock_five.png"},
        ]
    }
