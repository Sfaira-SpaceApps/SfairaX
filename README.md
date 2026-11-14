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

The image playback demo uses bundled PNGs returned by `/images`; it needs no
database or environment variables. `/spherexpng` remains a placeholder and does
not yet generate a valid PNG. Wise and Gaia are not implemented.

Vercel sets `VERCEL=1`. In that environment, `main.py` skips NiceGUI's internal
CPU process pool setup because the runtime lacks multiprocessing semaphores.
This is a compatibility workaround for NiceGUI 4; recheck it when upgrading
NiceGUI. Do not use `run.cpu_bound` on this deployment. Async HTTP requests and
the playback timer do not require this pool.

After deploying a preview, verify Load images, Play/Pause, frame stepping, and
the FPS slider. Also test refreshing and reconnecting: NiceGUI keeps page state
in the Python process, and a reconnect to a different instance can lose that
state. A passing HTTP smoke check does not verify the live UI connection.
