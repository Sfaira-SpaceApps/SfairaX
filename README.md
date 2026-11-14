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

