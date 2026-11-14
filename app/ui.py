import httpx
from fastapi import FastAPI
from nicegui import ui

def register_ui(app: FastAPI):
    @ui.page("/")
    def index():
        result = ui.label("Click button to load a result")

        right_angle = ui.number(label="Right Angle", value=0, format='%.2f')
        declination = ui.number(label="Declination", value=0, format='%.2f')
        color_theme = ui.select(["plasma", "viridis", "inferno", "magma"], label="Color Theme", value="plasma")
        cutout_size = ui.number(label="Cutout Size", value=0, format='%.2f')


        date_input = ui.input('Date Range').classes('w-40')
        ui.date().props('range').bind_value(
            date_input,
            forward = lambda x: f'{x["from"]} - {x["to"]}' if x else '',
            backward = lambda x: {
                'from': x.split(' - ')[0],
                'to': x.split(' - ')[1],
            } if ' - ' in x else None,
        )

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

        button = ui.button("Load result", on_click=fetch_hello)

        async def fetch_spherexpng():
            # Implement the logic to fetch the spherexpng image here
            result.set_text("loading...")
            button.disable()

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://internal"
                ) as client:
                    response = await client.get(
                        "/spherexpng",
                        params={
                            "ra_deg": right_angle.value,
                            "dec_deg": declination.value,
                            "cutout_size_i": cutout_size.value,
                            "fake_color_theme": color_theme.value,
                        },
                    )
                    response.raise_for_status()
                    result.set_text(response.text)
            except httpx.HTTPError:
                result.set_text("Failed to load result")
            finally:
                button.enable()



    ui.run_with(app)