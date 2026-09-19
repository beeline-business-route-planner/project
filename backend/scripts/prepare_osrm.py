#!/usr/bin/env python3
"""Prepare an immutable, fingerprinted OSRM graph without modifying running data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

IMAGE = "ghcr.io/project-osrm/osrm-backend@sha256:8a1b1bc938412f15f9b5b32d794c4ec6bf4a85dfbbabfa0a014b70b187edb53b"


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pbf", type=Path)
    source.add_argument("--url")
    parser.add_argument(
        "--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data/osrm"
    )
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    memory = int(
        subprocess.check_output(["docker", "info", "--format", "{{.MemTotal}}"], text=True).strip()
    )
    if memory < 2 * 1024**3:
        raise SystemExit("Docker needs at least 2 GiB RAM; large extracts need substantially more")
    print(
        f"Docker RAM: {memory / 1024**3:.1f} GiB; preprocessing threads: {args.threads}", flush=True
    )
    pbf = args.pbf.resolve() if args.pbf else data_dir / "download.osm.pbf"
    if args.url:
        download = data_dir / "download.osm.pbf.partial"
        with (
            urllib.request.urlopen(args.url, timeout=30) as response,
            download.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        os.replace(download, pbf)
    if not pbf.is_file():
        raise SystemExit("PBF file does not exist")
    minimum_disk = max(3 * 1024**3, pbf.stat().st_size * 20)
    if shutil.disk_usage(data_dir).free < minimum_disk:
        raise SystemExit(
            f"Need at least {minimum_disk / 1024**3:.1f} GiB free disk for this extract"
        )
    subprocess.run(
        ["docker", "image", "inspect", args.image], check=True, stdout=subprocess.DEVNULL
    )
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True
    ).strip()
    profile = subprocess.check_output(["docker", "run", "--rm", args.image, "cat", "/opt/car.lua"])
    version = subprocess.check_output(
        ["docker", "run", "--rm", args.image, "osrm-routed", "--version"], text=True
    ).strip()
    manifest = {
        "pbf_sha256": checksum(pbf),
        "image": args.image,
        "image_id": image_id,
        "osrm_version": version,
        "profile": "car",
        "profile_sha256": hashlib.sha256(profile).hexdigest(),
        "algorithm": "mld",
        "options": {"profile": "/opt/car.lua"},
    }
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    manifest["fingerprint"] = fingerprint
    final = data_dir / fingerprint
    if not (final / "manifest.json").is_file():
        staging = Path(tempfile.mkdtemp(prefix=".prepare-", dir=data_dir))
        try:
            shutil.copy2(pbf, staging / "region.osm.pbf")
            for command in (
                [
                    "osrm-extract",
                    "-t",
                    str(args.threads),
                    "-p",
                    "/opt/car.lua",
                    "/data/region.osm.pbf",
                ],
                ["osrm-partition", "-t", str(args.threads), "/data/region.osrm"],
                ["osrm-customize", "-t", str(args.threads), "/data/region.osrm"],
            ):
                subprocess.run(
                    ["docker", "run", "--rm", "-v", f"{staging}:/data", args.image, *command],
                    check=True,
                )
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            staging.rename(final)
        except BaseException:
            print(f"Preparation failed; diagnostic files preserved at {staging}", flush=True)
            raise
    print(f"OSRM_DATA_DIR={final}", flush=True)
    print(f"OSRM_GRAPH_FINGERPRINT={fingerprint}", flush=True)
    print(
        "Use this immutable directory for both OSRM and API; restart both when changing graph.",
        flush=True,
    )


if __name__ == "__main__":
    main()
