from io import BytesIO
from threading import Lock
from pathlib import Path
from typing import Union, Optional, Tuple
from datetime import datetime, date
import re
import json
import logging
import time
import requests

import pyvo
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from astropy.io import fits
from astropy.table import Table
from astropy.visualization import simple_norm
import matplotlib

matplotlib.use("Agg")  # Render on the server without a graphical display.
import matplotlib.pyplot as plt
import numpy as np


class SpherexNotFoundError(Exception):
    """No spectral image overlaps the requested position."""


class SpherexUpstreamError(Exception):
    """IRSA could not supply a usable spectral image."""


_render_lock = Lock()  # Protect pyplot's shared state during concurrent requests.
_examples_dir = Path(__file__).resolve().parents[1] / "data" / "spherex_examples"
logger = logging.getLogger(__name__)
EXAMPLE_MESSAGE = (
    "IRSA unavailable — displaying example SPHEREx data. Requested coordinates, "
    "size and dates do not apply; example exposures have different pointings."
)


class _BoundedSession(requests.Session):
    """Apply timeouts to PyVO's catalog and capability requests alike."""

    def request(self, method, url, **kwargs):
        kwargs["timeout"] = (3, 8)
        return super().request(method, url, **kwargs)


def example_manifest():
    return json.loads((_examples_dir / "manifest.json").read_text(encoding="utf-8"))


def example_frame(artifact_uri):
    for frame in example_manifest()["frames"]:
        if frame["id"] == artifact_uri:
            return frame
    raise ValueError("Unknown SPHEREx example ID.")


def example_observations():
    """Fixed examples deliberately ignore the requested sky position and dates."""
    rows = Table(rows=[
        (frame["id"], frame["id"], frame["mjd"], frame["bandpass"])
        for frame in example_manifest()["frames"]
    ], names=("artifact_uri", "download_url", "time_bounds_lower", "energy_bandpassname"))
    rows.sort("time_bounds_lower")
    rows.meta["source"] = "example"
    return rows


def render_available_frame(fits_url, fake_color_theme="gray", vmin=None, vmax=None):
    """Return (PNG, lower, upper, example metadata), falling back on I/O failure."""
    try:
        rendered = render_spherex_frame(fits_url, fake_color_theme, vmin, vmax)
        frame = example_frame(fits_url) if str(fits_url).startswith("example:") else None
    except SpherexUpstreamError:
        if str(fits_url).startswith("example:"):
            raise  # A broken deployment must not recurse into fallback.
        logger.warning("IRSA image unavailable; using bundled SPHEREx example.", exc_info=True)
        frame = example_manifest()["frames"][0]
        # Live-image brightness limits do not describe the substituted example.
        rendered = render_spherex_frame(frame["id"], fake_color_theme)
    return (*rendered, frame)


# ---------------------------------------------------------------------------
# Date → MJD conversion helpers
# ---------------------------------------------------------------------------

def date_to_mjd(date_input: Union[str, datetime, date, float, int, Time]) -> float:
    """
    Convert a user-friendly date into Modified Julian Date (MJD).

    Accepts:
      - ISO strings: "2025-05-01", "2025-05-01T12:00:00", "2025-05-01 12:00:00"
      - datetime / date objects
      - already-numeric MJD (just returns it)
      - astropy Time objects

    Returns
    -------
    float
        MJD value ready to pass to query_spherex(..., time_start=..., time_end=...)
    """
    if isinstance(date_input, (int, float)):
        # Already an MJD number
        return float(date_input)

    # Astropy accepts datetime objects, but plain dates need ISO conversion.
    if isinstance(date_input, date) and not isinstance(date_input, datetime):
        date_input = date_input.isoformat()

    # Let astropy parse almost anything sensible
    t = Time(date_input)
    return float(t.mjd)


def date_range_to_mjd(
    start: Union[str, datetime, date, float, int, Time],
    end: Optional[Union[str, datetime, date, float, int, Time]] = None,
) -> Tuple[float, Optional[float]]:
    """
    Convenience wrapper that returns (time_start, time_end) ready for query_spherex.

    Examples
    --------
    time_start, time_end = date_range_to_mjd("2025-05-01", "2025-08-31")
    time_start, time_end = date_range_to_mjd("2025-07-15")          # only start
    time_start, time_end = date_range_to_mjd(60800.0, 61000.0)      # already MJD
    """
    mjd_start = date_to_mjd(start)
    mjd_end = date_to_mjd(end) if end is not None else None
    return mjd_start, mjd_end


# ---------------------------------------------------------------------------
# Main query function
# ---------------------------------------------------------------------------

def query_spherex(
    ra_deg: float,
    dec_deg: float,
    cutout_size_i: float = 180.0,
    fake_color_theme: str = "gray",
    time_start: Union[str, datetime, date, float, int, Time, None] = None,
    time_end: Union[str, datetime, date, float, int, Time, None] = None,
) -> bytes:
    """
    Query SPHEREx data at an ICRS coordinate in degrees and return PNG bytes.

    Parameters
    ----------
    ra_deg, dec_deg : float
        Coordinates in degrees (ICRS).
    cutout_size_i : float
        Cutout size in arcsecs.
    fake_color_theme : str
        Matplotlib colormap name (e.g. "gray", "plasma", "viridis").
    time_start, time_end :
        Optional time bounds. Can be:
          - MJD float / int
          - ISO date string ("2025-05-01", "2025-08-15T12:00:00", ...)
          - datetime / date object
          - astropy Time object
        They are automatically converted to MJD.
    """
    if fake_color_theme not in matplotlib.colormaps:
        raise ValueError("Unknown fake_color_theme; use a Matplotlib colormap such as gray or plasma.")
    results_table = find_spherex_observations(
        ra_deg, dec_deg, cutout_size_i, time_start, time_end
    )
    png, _, _, _ = render_available_frame(str(results_table["download_url"][0]), fake_color_theme)
    return png


def find_spherex_observations(
    ra_deg, dec_deg, cutout_size_i=180.0, time_start=None, time_end=None,
    bandpass=None, artifact_uri=None,
):
    """Find chronological observations without downloading their images."""
    if not (np.isfinite(ra_deg) and 0 <= ra_deg < 360
            and np.isfinite(dec_deg) and -90 <= dec_deg <= 90
            and np.isfinite(cutout_size_i) and 0 < cutout_size_i <= 3600):
        raise ValueError("Invalid SPHEREx cutout coordinates or size.")
    coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    cutout_size = cutout_size_i * u.arcsec
    cutout_size_deg = cutout_size.to(u.deg).value
    time_start = date_to_mjd(time_start) if time_start is not None else None
    time_end = date_to_mjd(time_end) if time_end is not None else None
    if any(value is not None and not np.isfinite(value) for value in (time_start, time_end)):
        raise ValueError("Date bounds must be finite.")
    if time_start is not None and time_end is not None and time_start > time_end:
        raise ValueError("Start date must precede end date.")
    time_filter = ""
    if time_start is not None:
        time_filter += f" AND p.time_bounds_lower >= {time_start}"
    if time_end is not None:
        time_filter += f" AND p.time_bounds_lower <= {time_end}"
    if bandpass is not None:
        escaped_bandpass = bandpass.replace("'", "''")
        time_filter += f" AND p.energy_bandpassname = '{escaped_bandpass}'"
    if artifact_uri is not None:
        escaped_uri = artifact_uri.replace("'", "''")
        time_filter += f" AND a.uri = '{escaped_uri}'"
    query = f"""
SELECT DISTINCT
    a.uri AS artifact_uri,
    'https://irsa.ipac.caltech.edu/' || a.uri || '?center={coord.ra.value},{coord.dec.value}d&size={cutout_size_deg}' AS download_url,
    p.time_bounds_lower,
    p.energy_bandpassname
FROM spherex.artifact a
JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', {coord.ra.value}, {coord.dec.value}), p.poly)
{time_filter}
ORDER BY p.time_bounds_lower, download_url
"""
    try:
        with _BoundedSession() as session:
            service = pyvo.dal.TAPService("https://irsa.ipac.caltech.edu/TAP", session=session)
            response = service.search(query)
        if response.status[0] == "OVERFLOW":
            raise SpherexUpstreamError(
                "IRSA returned an incomplete result set. Please narrow the date range."
            )
        results = response.to_table()
    except SpherexUpstreamError:
        raise
    except Exception as exc:
        logger.warning("IRSA catalog unavailable; using bundled SPHEREx examples: %s", exc)
        return example_observations()
    if not len(results):
        raise SpherexNotFoundError("No SPHEREx data found coverage for this coordinate.")
    return results


def spherex_cutout_url(artifact_uri: str, ra_deg: float, dec_deg: float,
                      cutout_size_i: float = 180.0) -> str:
    """Build a cutout URL only for an IRSA SPHEREx FITS data path.

    This is stateless: any API instance can resolve the artifact supplied by
    the manifest without querying TAP again or maintaining an in-memory cache.
    """
    cutout_size = cutout_size_i * u.arcsec
    cutout_size_deg = cutout_size.to(u.deg).value
    if (
        not re.fullmatch(r"ibe/data/spherex/[A-Za-z0-9_./-]+\.fits", artifact_uri)
        or any(part in ("", ".", "..") for part in artifact_uri.split("/"))
    ):
        raise ValueError("Invalid SPHEREx artifact path. Query observations again.")
    if not (np.isfinite(ra_deg) and 0 <= ra_deg < 360
            and np.isfinite(dec_deg) and -90 <= dec_deg <= 90
            and np.isfinite(cutout_size_i) and 0 < cutout_size_i <= 3600):
        raise ValueError("Invalid SPHEREx cutout coordinates or size.")
    return (
        f"https://irsa.ipac.caltech.edu/{artifact_uri}"
        f"?center={ra_deg},{dec_deg}d&size={cutout_size_deg}"
    )


def render_spherex_frame(fits_url, fake_color_theme="gray", vmin=None, vmax=None):
    """Render a frame, returning PNG bytes and reusable brightness limits."""
    if fake_color_theme not in matplotlib.colormaps:
        raise ValueError("Unknown fake_color_theme; use a Matplotlib colormap such as gray or plasma.")
    if (vmin is None) != (vmax is None):
        raise ValueError("Supply both brightness limits together.")
    if vmin is not None and (not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax):
        raise ValueError("Brightness limits must be finite and increasing.")
    example = example_frame(fits_url) if str(fits_url).startswith("example:") else None
    try:
        if example:
            source = _examples_dir / example["file"]
        else:
            # Bound both input size and network time; never cache full exposures
            # or depend on another Vercel instance's temporary files.
            started = time.monotonic()
            content = bytearray()
            with requests.get(fits_url, stream=True, timeout=(3, 8)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(64 * 1024):
                    content.extend(chunk)
                    if len(content) > 8 * 1024 * 1024 or time.monotonic() - started > 15:
                        raise SpherexUpstreamError("IRSA cutout exceeded download budget.")
            source = BytesIO(content)
        with fits.open(source, cache=False) as hdul:
            data = hdul["IMAGE"].data.astype(np.float32)
    except Exception as e:
        raise SpherexUpstreamError("Error streaming or opening SPHEREx FITS file.") from e

    if not np.any(np.isfinite(data)):
        raise SpherexUpstreamError("SPHEREx image contains no usable pixels.")
    norm = simple_norm(data, stretch="asinh", percent=99.5, vmin=vmin, vmax=vmax)
    if norm.vmin == norm.vmax:
        norm.vmax = norm.vmin + max(abs(norm.vmin) * 0.01, 1e-6)

    with _render_lock:
        fig, ax = plt.subplots(figsize=(8, 8))
        try:
            im = ax.imshow(data, origin="lower", cmap=fake_color_theme, norm=norm)
            plt.colorbar(im, ax=ax, label="MJy/sr")

            title = "SPHEREx Spectral Image"
            if example:
                title = ("EXAMPLE DATA — requested position/dates do not apply\n"
                         f"RA {example['ra_deg']:.5f}°, Dec {example['dec_deg']:.5f}°\n"
                         f"{example['date']} | {example['bandpass']}")
            ax.set_title(title, fontsize=10 if example else 12)
            ax.axis("off")
            # Return the PNG to the endpoint instead of writing output.png.
            with BytesIO() as output:
                plt.savefig(output, format="png", dpi=150, bbox_inches="tight")
                return output.getvalue(), float(norm.vmin), float(norm.vmax)
        finally:
            plt.close(fig)



# Unnecessary for the actual API, but needed for the the local test.
# ---------------------------------------------------------------------------
# Automatic test runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example coordinates from official IRSA / SPHEREx tutorials
    TEST_RA = 210.80227
    TEST_DEC = 54.34895

    # Human-readable dates – these will be automatically converted to MJD
    TEST_DATE_START = "2025-05-01"
    TEST_DATE_END = "2025-12-31"

    print("=" * 60)
    print("Running SPHEREx query test")
    print(f"  RA, Dec          = {TEST_RA}, {TEST_DEC}")
    print(f"  Cutout size      = 180 arcsec")
    print(f"  Colormap         = plasma")
    print(f"  Date range       = {TEST_DATE_START} → {TEST_DATE_END}")

    # Show the converted MJD values for transparency
    mjd_start, mjd_end = date_range_to_mjd(TEST_DATE_START, TEST_DATE_END)
    print(f"  Converted MJD    = {mjd_start:.3f} → {mjd_end:.3f}")
    print("=" * 60)

    try:
        png_bytes = query_spherex(
            ra_deg=TEST_RA,
            dec_deg=TEST_DEC,
            cutout_size_i=180.0,
            fake_color_theme="plasma",
            time_start=TEST_DATE_START,   # can pass the string directly
            time_end=TEST_DATE_END,       # conversion happens inside query_spherex
        )

        out_path = Path("spherex_test_output.png")
        out_path.write_bytes(png_bytes)
        print(f"\n✅ Success! Wrote {len(png_bytes):,} bytes → {out_path.resolve()}")
    except SpherexNotFoundError as e:
        print(f"\n❌ No data found: {e}")
    except SpherexUpstreamError as e:
        print(f"\n❌ Upstream / network error: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected error: {type(e).__name__}: {e}")
