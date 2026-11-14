from datetime import date

import httpx
from fastapi import FastAPI
from nicegui import ui

def register_ui(app: FastAPI):
    @ui.page("/")
    def index():
        result = ui.label("Click button to load a result")
        with ui.row().classes("items-center gap-4"):
            dataset = ui.select(["SphereX", "Wise", "Gaia", "Hello"], label="Dataset", value="SphereX")

            right_angle = ui.number(label="Right Angle", value=0, format='%.2f')
            declination = ui.number(label="Declination", value=0, format='%.2f')
            color_theme = ui.select(["plasma", "viridis", "inferno", "magma"], label="Color Theme", value="plasma")
            cutout_size = ui.number(
                label="Cutout Size (arcsec)", value=0.05, min=0.01, max=1,
                step=0.01, format='%.2f',
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
            elif dataset.value == "Hello":
                await fetch_hello()
            else:
                result.set_text("Unsupported dataset")

        button = ui.button("Load result", on_click=fetch_from_dataset)

        ui.label("Image playback").classes("text-xl font-bold")
        frames = []
        frame_index = 0

        image = ui.image().classes("w-full max-w-xl")
        image.set_visibility(False)
        frame_label = ui.label("Load images to begin playback.")

        ui.label("Playback frame rate")
        frame_rate_slider = ui.slider(min=1, max=30, value=2, step=1).classes(
            "w-64"
        ).props("label")

        def show_frame():
            frame = frames[frame_index]
            image.set_source(frame["src"])
            image.set_visibility(True)
            frame_label.set_text(
                f'{frame_index + 1} / {len(frames)} — {frame.get("date", "")}'
            )

        def prev_frame():
            nonlocal frame_index
            if frames:
                frame_index = (frame_index - 1) % len(frames)
                show_frame()

        def next_frame():
            nonlocal frame_index
            if frames:
                frame_index = (frame_index + 1) % len(frames)
                show_frame()



        timer = ui.timer(1 / frame_rate_slider.value, next_frame, active=False)
        ui.label().bind_text_from(
            frame_rate_slider, "value", backward=lambda value: f"{value:g} FPS"
        )

        def update_frame_rate():
            timer.interval = 1 / frame_rate_slider.value

        frame_rate_slider.on_value_change(update_frame_rate)


        async def load_images(mock=False):
            nonlocal frames, frame_index
            timer.deactivate()
            load_button.disable()
            button.disable()
            play_button.disable()
            pause_button.disable()
            frame_label.set_text("Loading images...")

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://internal",
                    timeout=120,
                ) as client:
                    if mock:
                        response = await client.get("/images")
                    else:
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
                if not mock:
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

                frames = loaded_frames
                frame_index = 0
                if frames:
                    show_frame()
                    play_button.enable()
                    pause_button.enable()
                    result.set_text(f"Loaded {len(frames)} frames.")
                else:
                    image.set_visibility(False)
                    frame_label.set_text("No images returned.")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                frames = []
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
                load_button.enable()
                button.enable()

        with ui.row().classes("items-center gap-4"):
            async def load_mock_images():
                await load_images(mock=True)

            load_button = ui.button("Load mock images", on_click=load_mock_images)
            play_button = ui.button("Play", on_click=timer.activate)
            pause_button = ui.button("Pause", on_click=timer.deactivate)
            ui.button("<", on_click=prev_frame)
            ui.button(">", on_click=next_frame)
            play_button.disable()
            pause_button.disable()

    ui.run_with(app)
