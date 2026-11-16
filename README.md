# Sfaira

FastAPI and NiceGUI astronomy image viewer.

## Local development

Use Python 3.12:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn main:app --reload
```

## Vercel preview

Import the repository and select the directory containing this README as the
Root Directory. Use the FastAPI framework preset and leave build and output
directory overrides unset. Vercel detects `main.py:app` and installs production
dependencies from `pyproject.toml`. Enable Fluid compute for WebSocket support.

## SPHEREx outage fallback

`query_spherex(..., cutout_size_i=180.0)` and all SPHEREx API endpoints accept
cutout size in **arcseconds**, defaulting to 180 and allowing sizes greater than
zero up to 3600. The service converts arcseconds to degrees when constructing
IRSA cutout URLs (180 arcseconds becomes `size=0.05`). Bundled outage examples
have a fixed size, as indicated by the fallback warning.

Playback downloads all frames up front (up to three simultaneous requests) and
waits until every image has decoded before enabling Play. Play, Pause, stepping,
and timing run in the browser, reusing those decoded images without per-frame
server requests. Initial loading can take longer for large sequences. A 128 MiB
browser budget includes downloaded images and decoded pixels; sequences above
that budget ask for a shorter date range. Loading a new sequence or leaving the
page releases the previous images.

The browser playback checks can be run with Node.js:

```sh
node --test tests/playback.test.cjs
```

The app tries IRSA first. Catalog network/service failures or an unusable image
download switch to real, bundled SPHEREx QR2 example cutouts. Successful empty
queries still report no coverage; invalid inputs and catalog result overflow
remain errors. Examples ignore the requested coordinates, size and dates.
The observations response includes `source: "example"`, a warning, and actual
coordinates, dates and S3 source links for every frame. The UI displays the
warning. Every example PNG is also labeled with its actual coordinates and time,
including when an image download fails after a successful catalog query.
Frame responses expose `X-SPHEREx-Source` and, for examples,
`X-SPHEREx-Example-ID` alongside the existing brightness headers.

The three 128-by-128 FITS cutouts in `app/data/spherex_examples/` retain calibrated
MJy/sr pixels, flags and celestial WCS. They show consecutive exposures with
different pointings; they are illustrative frames, not a registered time series.
The `detector-2` label identifies the detector, not a monochromatic bandpass.
The source keys are under `s3://nasa-irsa-spherex/qr2/level2/` and are recorded in
`manifest.json`.

To regenerate the examples locally with the project dependencies installed:

```sh
python scripts/prepare_spherex_examples.py
```

Preparation downloads three full exposures (about 72 MB each) to ignored
`build/`. Production only reads the bundled cutouts; it needs no S3 credentials,
bucket search, runtime downloads of examples, or persistent filesystem/cache.
Setuptools includes the FITS and manifest files as package data, and `vercel.json`
explicitly includes them in the FastAPI function. `.vercelignore` excludes the
full-exposure downloads in `build/`.

IRSA calls use 3-second connection and 8-second read timeouts. Image downloads
also have an 8 MiB input cap and a 15-second elapsed budget checked between
chunks. These are per-call limits, not an overall request deadline. PNG responses
are generated one frame at a time; fallback response size is tested below
Vercel's 4.5 MB buffered response limit.

Run the fallback checks without access to IRSA or S3:

```sh
python -m pytest
```

