from unittest.mock import Mock, MagicMock

import pytest
import requests
from astropy.io import fits
from astropy.table import Table
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import router
from app.services import spherex_service as service


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def outage(monkeypatch):
    tap = Mock(side_effect=requests.Timeout("IRSA unavailable"))
    monkeypatch.setattr(service.pyvo.dal, "TAPService", tap)
    return tap


def test_catalog_outage_returns_real_examples(client, outage, monkeypatch):
    # Dates deliberately outside example coverage: the substitution is explicit.
    response = client.get("/spherex/observations", params=dict(
        ra_deg=0, dec_deg=0, time_start="2026-01-01", time_end="2026-01-02"))
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["source"] == "example"
    assert "Requested coordinates" in manifest["message"]
    assert len(manifest["frames"]) == 3
    assert all(frame["source_url"].startswith(
        "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr2/level2/"
    ) for frame in manifest["frames"])

    # Rendering the returned ID is stateless and requires no catalog or S3 I/O.
    monkeypatch.setattr(service.requests, "get", Mock(side_effect=AssertionError("network")))
    outage.reset_mock()
    frame = client.get(manifest["frames"][0]["image_url"])
    assert frame.status_code == 200
    assert frame.content.startswith(b"\x89PNG")
    assert len(frame.content) < 4_500_000
    assert frame.headers["X-SPHEREx-Source"] == "example"
    assert float(frame.headers["X-Image-Vmin"]) < float(frame.headers["X-Image-Vmax"])
    outage.assert_not_called()


def test_primary_query_falls_back(outage):
    assert service.query_spherex(0, 0).startswith(b"\x89PNG")


def test_successful_live_query_is_preserved(monkeypatch):
    rows = Table(rows=[("ibe/data/spherex/test.fits", "https://example.test/frame", 60800., "1")],
                 names=("artifact_uri", "download_url", "time_bounds_lower", "energy_bandpassname"))
    response = Mock(status=("OK",), to_table=Mock(return_value=rows))
    monkeypatch.setattr(service.pyvo.dal, "TAPService", Mock(return_value=Mock(
        search=Mock(return_value=response))))
    assert service.find_spherex_observations(0, 0) is rows


def test_empty_success_is_not_an_outage(monkeypatch):
    response = Mock(status=("OK",), to_table=Mock(return_value=Table()))
    monkeypatch.setattr(service.pyvo.dal, "TAPService", Mock(return_value=Mock(
        search=Mock(return_value=response))))
    with pytest.raises(service.SpherexNotFoundError):
        service.find_spherex_observations(0, 0)


def test_overflow_keeps_narrow_date_range_error(monkeypatch):
    monkeypatch.setattr(service.pyvo.dal, "TAPService", Mock(return_value=Mock(
        search=Mock(return_value=Mock(status=("OVERFLOW",))))))
    with pytest.raises(service.SpherexUpstreamError, match="narrow"):
        service.find_spherex_observations(0, 0)


@pytest.mark.parametrize("params", [
    {"ra_deg": 360}, {"dec_deg": 91},
    {"time_start": "2026-02-01", "time_end": "2026-01-01"},
    {"fake_color_theme": "invalid"},
])
def test_invalid_requests_never_fall_back(client, outage, params):
    query = dict(ra_deg=0, dec_deg=0, time_start="2026-01-01", time_end="2026-01-02")
    query.update(params)
    assert client.get("/spherex/observations", params=query).status_code == 422
    outage.assert_not_called()


def test_image_failure_after_catalog_success_is_labeled(client, monkeypatch):
    monkeypatch.setattr(service.requests, "get", Mock(side_effect=requests.Timeout()))
    response = client.get("/spherex/frame", params=dict(
        ra_deg=0, dec_deg=0, mjd=60800, bandpass="1",
        artifact_uri="ibe/data/spherex/test.fits"))
    assert response.status_code == 200
    assert response.headers["X-SPHEREx-Source"] == "example"
    assert response.headers["X-SPHEREx-Example-ID"] == "example:1"
    assert response.content.startswith(b"\x89PNG")


def test_live_image_download_keeps_live_source(client, monkeypatch):
    example = service.example_manifest()["frames"][0]
    content = (service._examples_dir / example["file"]).read_bytes()
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [content]
    get = Mock(return_value=response)
    monkeypatch.setattr(service.requests, "get", get)
    frame = client.get("/spherex/frame", params=dict(
        ra_deg=0, dec_deg=0, mjd=60800, bandpass="1",
        artifact_uri="ibe/data/spherex/test.fits"))
    assert frame.status_code == 200
    assert frame.headers["X-SPHEREx-Source"] == "irsa"
    assert "X-SPHEREx-Example-ID" not in frame.headers
    assert frame.content.startswith(b"\x89PNG")
    assert get.call_args.kwargs["timeout"] == (3, 8)
    response.raise_for_status.assert_called_once()


def test_oversized_image_download_uses_example(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [b"0" * (8 * 1024 * 1024 + 1)]
    monkeypatch.setattr(service.requests, "get", Mock(return_value=response))
    png, _, _, example = service.render_available_frame("https://example.test/cutout.fits")
    assert png.startswith(b"\x89PNG")
    assert example["id"] == "example:1"


def test_example_ids_cannot_access_arbitrary_files(client):
    response = client.get("/spherex/frame", params=dict(
        ra_deg=0, dec_deg=0, mjd=60800, bandpass="1", artifact_uri="example:../../main.py"))
    assert response.status_code == 422


def test_examples_have_usable_data_and_preserved_coordinates():
    import numpy as np
    from astropy.wcs import WCS

    for frame in service.example_manifest()["frames"]:
        with fits.open(service._examples_dir / frame["file"], checksum=True) as hdul:
            image = hdul["IMAGE"]
            assert image.data.shape == (128, 128)
            assert np.isfinite(image.data).any()
            ra, dec = WCS(image.header).pixel_to_world_values(63.5, 63.5)
            assert ra == pytest.approx(frame["ra_deg"])
            assert dec == pytest.approx(frame["dec_deg"])


def test_pyvo_session_always_sets_network_timeout(monkeypatch):
    request = Mock()
    monkeypatch.setattr(requests.Session, "request", request)
    with service._BoundedSession() as session:
        session.get("https://example.test", timeout=None)
    assert request.call_args.kwargs["timeout"] == (3, 8)


@pytest.mark.parametrize("size", [180, 3600])
def test_api_passes_arcseconds_to_service(client, monkeypatch, size):
    query = Mock(return_value=b"png")
    monkeypatch.setattr(service, "query_spherex", query)
    response = client.get("/spherexpng", params=dict(ra_deg=0, dec_deg=0, cutout_size_i=size))
    assert response.status_code == 200
    assert query.call_args.args[2] == size


def test_default_size_is_180_arcseconds(client, monkeypatch):
    query = Mock(return_value=b"png")
    monkeypatch.setattr(service, "query_spherex", query)
    assert client.get("/spherexpng", params=dict(ra_deg=0, dec_deg=0)).status_code == 200
    assert query.call_args.args[2] == 180


def test_cutout_url_converts_arcseconds_to_degrees():
    from urllib.parse import parse_qs, urlparse

    url = service.spherex_cutout_url("ibe/data/spherex/test.fits", 0, 0, 180)
    assert float(parse_qs(urlparse(url).query)["size"][0]) == pytest.approx(0.05)


@pytest.mark.parametrize("size", [0, -1, 3601])
def test_api_rejects_invalid_cutout_sizes(client, size):
    assert client.get("/spherexpng", params=dict(
        ra_deg=0, dec_deg=0, cutout_size_i=size)).status_code == 422
