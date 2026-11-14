from fastapi import FastAPI
import logging
import os
import importlib
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from nicegui import dependencies, run
from nicegui.element import Element

from app.api.endpoints import router
from app.ui import register_ui


if os.environ.get("VERCEL") == "1":
    # Register modules in every instance, including instances whose first
    # request is for JavaScript rather than the page itself.
    for module_name in ("select", "input", "image", "timer"):
        importlib.import_module(f"nicegui.elements.{module_name}")

    _hash_file_path = dependencies.hash_file_path

    def stable_dependency_hash(path: Path, *, max_time: float | None = None) -> str:
        return _hash_file_path(path, max_time=None)

    dependencies.hash_file_path = stable_dependency_hash
    dependencies.compute_key.cache_clear()

    # Dependency extraction timestamps can differ across Vercel instances.
    # NiceGUI includes those timestamps in component keys by default, causing
    # HTML from one instance to reference unknown modules on another instance.
    for registry in (dependencies.js_components, dependencies.vue_components):
        components = list(registry.values())
        registry.clear()
        for component in components:
            old_key = component.key
            component.key = dependencies.compute_key(component.path, max_time=None)
            dependencies.Component._keys.discard(old_key)
            dependencies.Component._keys.add(component.key)
            registry[component.key] = component

    # Element subclasses copy their component metadata at class creation.
    # Update those copies as well as the registries used to serve modules.
    def stabilize_element_components(element_class: type) -> None:
        component = element_class.component
        if component is not None:
            component.key = dependencies.compute_key(component.path, max_time=None)
        for subclass in element_class.__subclasses__():
            stabilize_element_components(subclass)

    stabilize_element_components(Element)

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
