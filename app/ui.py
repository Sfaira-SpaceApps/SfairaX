from datetime import date
import json

import httpx
from fastapi import FastAPI
from nicegui import ui

def register_ui(app: FastAPI):
    @ui.page("/")
    def index():
        ui.add_head_html('<script src="/assets/js/playback.js"></script>')
        result = ui.label("Click button to load a result")
        with ui.row().classes("items-center gap-4"):
            dataset = ui.select(["SphereX", "Wise", "Gaia", "Hello"], label="Dataset", value="SphereX")

            right_angle = ui.number(label="Right Angle", value=0, format='%.2f')
            declination = ui.number(label="Declination", value=0, format='%.2f')
            color_theme = ui.select(["plasma", "viridis", "inferno", "magma"], label="Color Theme", value="plasma")
            cutout_size = ui.number(
                label="Cutout Size (arcsec)", value=180, min=1, max=3599,
                step=1, format='%.2f',
            )

            with ui.input(
                "Date range",
                placeholder="YYYY-MM-DD - YYYY-MM-DD",
            ).classes("w-80") as date_input:
                with ui.menu().props("no-parent-event no-focus") as menu:
                    calendar = ui.date().props("range minimal")

                    calendar.bind_value(
                        date_input,
                        forward=lambda value: (
                            f'{value["from"]} - {value["to"]}'
                            if isinstance(value, dict) else value
                        ),
                        backward=lambda value: (
                            dict(zip(("from", "to"), value.split(" - ")))
                            if value and " - " in value else None
                        ),
                    )

                    ui.button("Done", on_click=menu.close).props("flat")

                date_input.on("focus", menu.open)
                date_input.on("click", menu.open)

            '''date_input = ui.input('Date Range').classes('w-40')
            ui.date().props('range').bind_value(
                date_input,
                forward = lambda x: f'{x["from"]} - {x["to"]}' if x else '',
                backward = lambda x: {
                    'from': x.split(' - ')[0],
                    'to': x.split(' - ')[1],
                } if ' - ' in x else None,
            )'''

        async def fetch_hello():
            result.set_text("loading...")
            button.disable()

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://internal"
                ) as client:
                    response = await client.get(
                        "/hello",
                        params={"number": right_angle.value},
                    )
                    response.raise_for_status()
                    result.set_text(response.text)
            except httpx.HTTPError:
                result.set_text("Failed to load result")
            finally:
                button.enable()


        async def fetch_spherexpng():
            await load_images()

        async def fetch_from_dataset():
            if dataset.value == "SphereX":
                await fetch_spherexpng()
            
            else:
                result.set_text("Unsupported dataset")

        button = ui.button("Load result", on_click=fetch_from_dataset)

        ui.label("Image playback").classes("text-xl font-bold")
        image = ui.element("div").classes("w-full max-w-xl")
        image.set_visibility(False)
        frame_label = ui.label("Load images to begin playback.")

        ui.label("Playback frame rate")
        frame_rate_slider = ui.slider(min=1, max=30, value=2, step=1).classes(
            "w-64"
        ).props("label")

        ui.label().bind_text_from(
            frame_rate_slider, "value", backward=lambda value: f"{value:g} FPS"
        )

        frame_rate_slider.on(
            "update:model-value", js_handler="value => window.SpherexPlayback.setRate(value)"
        )


        async def load_images():
            ui.run_javascript("window.SpherexPlayback.pause()")
            button.disable()
            play_button.disable()
            pause_button.disable()
            prev_button.disable()
            next_button.disable()
            image.set_visibility(False)
            frame_label.set_text("Loading images...")

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://internal",
                    timeout=120,
                ) as client:
                    date_parts = (date_input.value or "").split(" - ")
                    if len(date_parts) != 2:
                        raise ValueError("Enter a start and end date: YYYY-MM-DD - YYYY-MM-DD.")
                    try:
                        start, end = [date.fromisoformat(part.strip()) for part in date_parts]
                    except ValueError:
                        raise ValueError("Enter valid dates in YYYY-MM-DD format.") from None
                    if start > end:
                        raise ValueError("Start date must precede end date.")
                    response = await client.get(
                        "/spherex/observations",
                        params={
                            "ra_deg": right_angle.value,
                            "dec_deg": declination.value,
                            "cutout_size_i": cutout_size.value,
                            "fake_color_theme": color_theme.value,
                            "time_start": start.isoformat(),
                            "time_end": end.isoformat(),
                        },
                    )
                    response.raise_for_status()

                loaded_frames = response.json()["frames"]
                loaded_frames = [
                    {**frame, "src": frame["image_url"]}
                    for frame in sorted(loaded_frames, key=lambda frame: frame["mjd"])
                ]
                if not isinstance(loaded_frames, list) or any(
                    not isinstance(frame, dict)
                    or not isinstance(frame.get("src"), str)
                    or not frame["src"]
                    for frame in loaded_frames
                ):
                    raise ValueError("Invalid image frames")

                if loaded_frames:
                    frame_label.set_text(f"Downloading {len(loaded_frames)} images before playback...")
                    preload = await ui.run_javascript(
                        f"return await window.SpherexPlayback.load({json.dumps(loaded_frames)}, "
                        f"{json.dumps(image.html_id)}, {json.dumps(frame_label.html_id)})",
                        timeout=130,
                    )
                    if preload.get("error"):
                        raise ValueError(preload["error"])
                    image.set_visibility(True)
                    play_button.enable()
                    pause_button.enable()
                    prev_button.enable()
                    next_button.enable()
                    message = response.json().get("message")
                    if preload.get("example") and not message:
                        message = "IRSA image unavailable — displaying labeled example data."
                    result.set_text(message or f"Loaded {len(loaded_frames)} frames. Ready for playback.")
                else:
                    image.set_visibility(False)
                    frame_label.set_text("No images returned.")
            except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError) as exc:
                image.set_visibility(False)
                message = "Failed to load images. Try again."
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        detail = exc.response.json().get("detail")
                        if isinstance(detail, str):
                            message = detail
                    except ValueError:
                        pass
                elif isinstance(exc, ValueError):
                    message = str(exc)
                frame_label.set_text(message)
                result.set_text(message)
            finally:
                button.enable()

        with ui.row().classes("items-center gap-4"):
            play_button = ui.button("Play").on(
                "click", js_handler="() => window.SpherexPlayback.play()")
            pause_button = ui.button("Pause").on(
                "click", js_handler="() => window.SpherexPlayback.pause()")
            prev_button = ui.button("<").on(
                "click", js_handler="() => window.SpherexPlayback.step(-1)")
            next_button = ui.button(">").on(
                "click", js_handler="() => window.SpherexPlayback.step(1)")
            play_button.disable()
            pause_button.disable()
            prev_button.disable()
            next_button.disable()

    ui.run_with(app)
