"""Prepare reproducible, small offline examples from public QR2 spectral images.

Run locally, never during a Vercel request. Downloads are kept in ignored build/.
"""
import json
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.time import Time
from astropy.wcs import WCS

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
PREFIX = "qr2/level2/2025W17_4B/l2b-v20-2025-240/2/"


def main():
    destination = ROOT / "app/data/spherex_examples"
    destination.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    frames = []
    # Three consecutive exposures on the same detector. Each cutout retains
    # its own pointing; these are illustrative frames, not a registered movie.
    for number in range(1, 4):
        filename = f"level2_2025W17_4B_0001_{number}D2_spx_l2b-v20-2025-240.fits"
        url = BASE + PREFIX + filename
        source = scratch / filename
        if not source.exists():
            with requests.get(url, stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                partial = source.with_suffix(".part")
                with partial.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
                if "Content-Length" in response.headers:
                    if partial.stat().st_size != int(response.headers["Content-Length"]):
                        raise RuntimeError(f"Incomplete download: {url}")
                partial.replace(source)
        with fits.open(source) as hdul:
            header = hdul["IMAGE"].header
            wcs = WCS(header)
            shape = hdul["IMAGE"].data.shape
            position = ((shape[1] - 1) / 2, (shape[0] - 1) / 2)
            cutout = Cutout2D(hdul["IMAGE"].data, position, (128, 128), wcs=wcs)
            # Keep the celestial WCS; omit alternate wavelength-table WCS
            # because the full-frame lookup extension is not bundled.
            image_header = cutout.wcs.to_header(relax=True)
            for key in ("BUNIT", "DETECTOR", "DATE-OBS", "MJD-OBS", "OBSID"):
                if key in header:
                    image_header[key] = header[key]
            flags = Cutout2D(hdul["FLAGS"].data, position, (128, 128))
            local_name = f"example-{number}.fits"
            fits.HDUList([
                fits.PrimaryHDU(header=hdul[0].header),
                fits.ImageHDU(cutout.data.astype(np.float32), header=image_header, name="IMAGE"),
                fits.ImageHDU(flags.data, name="FLAGS"),
            ]).writeto(destination / local_name, overwrite=True, checksum=True)
            primary = hdul[0].header
            ra, dec = wcs.pixel_to_world_values(*position)
            # Observation time is read from the source, never inferred from its key.
            observation_date = header.get("DATE-OBS", primary.get("DATE-OBS"))
            mjd = header.get("MJD-OBS", primary.get("MJD-OBS"))
            if mjd is None:
                mjd = Time(observation_date).mjd
            frames.append(dict(
                id=f"example:{number}", file=local_name, source_url=url,
                ra_deg=float(ra), dec_deg=float(dec),
                mjd=float(mjd), date=Time(float(mjd), format="mjd").isot + "Z",
                bandpass=f"detector-{header['DETECTOR']}",
            ))
            print(f"Prepared {local_name}: {ra:.5f}, {dec:.5f}, MJD {mjd}")
    manifest = dict(
        description="Real SPHEREx QR2 cutouts from consecutive exposures on the same detector; pointings differ. Detector labels are not monochromatic bandpasses.",
        frames=frames,
    )
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
