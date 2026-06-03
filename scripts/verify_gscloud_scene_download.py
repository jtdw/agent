from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.domestic_sources.gscloud_download_verifier import to_json, verify_gscloud_scene_download
from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify one GSCloud scene-table product download path.")
    parser.add_argument("--product-key", required=True, choices=sorted(GSCLOUD_PRODUCTS.keys()))
    parser.add_argument("--storage-state", required=True, help="Playwright storage_state JSON path.")
    parser.add_argument("--download-dir", default="workspace/gscloud_download_verification")
    parser.add_argument("--execute-download", action="store_true", help="Actually click one download button and validate the saved file.")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--region", default="")
    parser.add_argument("--year", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--cloud-max", type=float, default=30.0)
    parser.add_argument("--processing-level", default="")
    parser.add_argument("--include-qc", action="store_true")
    parser.add_argument("--include-quality", action="store_true")
    args = parser.parse_args()

    result = verify_gscloud_scene_download(
        product_key=args.product_key,
        storage_state_path=args.storage_state,
        download_dir=args.download_dir,
        execute_download=args.execute_download,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout_seconds,
        headless=not args.headed,
        options={
            "region": args.region,
            "year": args.year,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "cloud_max": args.cloud_max,
            "processing_level": args.processing_level,
            "include_qc": args.include_qc,
            "include_quality": args.include_quality,
        },
    )
    print(to_json(result))


if __name__ == "__main__":
    main()
