# GSCloud Scene Pagination Design

## Goal

Make GSCloud scene-table downloads search beyond the first visible page. The current scene downloaders mainly inspect the first 200-240 rendered rows. This misses records when products have many pages, especially Sentinel-2.

This phase adds a reusable scene-table pagination helper and applies it to Sentinel-2 first.

## Scope

Included:

- Reusable table row discovery for GSCloud scene product pages.
- Reusable best-effort "next page" click behavior.
- Page scanning with `max_pages`.
- Candidate collection with `page_no`, `row_index`, `row_text`, parsed metadata, and skip reason.
- Sentinel-2 downloader migration to use the reusable scanner.
- Status updates for `pages_scanned`, `candidate_count`, and selected scene count.
- Tests for pagination selection logic and Sentinel-2 scanner integration at the pure-function/helper level.

Excluded:

- AOI geometry coverage checks.
- Raster/vector clipping.
- Frontend redesign.
- SQLite persistent scene index.
- Bulk migration of every MODIS and Landsat downloader in the same change.
- Live GSCloud end-to-end download tests, because they depend on login state and website availability.

## Existing Context

`core/domestic_sources/gscloud_indexer.py` already has DEM-oriented pagination helpers such as row discovery and next-page clicking. The scene-table products have separate downloaders that currently perform their own first-page row scans.

The new helper should borrow the proven pagination ideas without coupling scene products to DEM tile indexing.

## Architecture

Add `core/domestic_sources/gscloud_scene_table.py`.

Core types:

- `SceneTableRecord`: parsed row plus page metadata.
- `SceneTableScanResult`: records, pages scanned, stop reason, and row counts.

Core functions:

- `get_scene_table_rows(page)`: returns visible table rows using common table selectors.
- `click_next_scene_page(page)`: clicks a usable next-page control and returns whether navigation likely advanced.
- `scan_scene_table_pages(page, parse_row, max_pages, status_path=None)`: loops pages, calls product parser for each row, and returns parsed records.
- `select_scene_records(records, *, year, start_date, end_date, max_scenes, extra_filter=None)`: applies shared date/data-available filtering and product-specific filters.

Sentinel-2 flow:

1. Open `SENTINEL2_MSI.access_url`.
2. Select "data available" when possible.
3. Call `scan_scene_table_pages`.
4. Filter by data availability, year/date range, and optional processing level.
5. Revisit or stay on each selected page, locate the selected row by scene id, and click download.

For this phase, selected rows may be downloaded during the scan when a row passes filters. This is acceptable if it avoids unreliable page revisits. The implementation must still record the page metadata in the selected scene.

## Behavior

Default page limit:

- `max_pages=0` means use environment variable `GSCLOUD_SCENE_MAX_PAGES`, default `20`.
- Product start functions may later expose `max_pages`; this phase can use the default.

Stop conditions:

- Reached `max_pages`.
- No clickable next page.
- Repeated page signature detected.
- Enough scenes have been selected and downloaded.

Status:

- While scanning, write `state="SCANNING"` and update `pages_scanned`.
- When candidates are found, update `candidate_count`.
- When a selected record is downloaded, update selected/downloaded counts.

## Error Handling

If no selected records are found after scanning, the error should include:

- product name
- pages scanned
- active filters
- a hint to relax date, year, processing-level, or max page limits

The downloader must continue to require `data_available == "有"`.

## Tests

Add tests for:

- Sentinel-2 row parser remains correct.
- `select_scene_records` chooses records across multiple pages, not only page 1.
- It skips rows whose data availability is "无".
- It respects processing level filters such as `MSIL2A`.
- Low `max_scenes` stops selection at the requested count.

Run:

```powershell
python -m unittest tests.test_gscloud_scene_table tests.test_gscloud_sentinel2
python -m unittest discover tests
python -m py_compile core\domestic_sources\gscloud_scene_table.py core\domestic_sources\gscloud_sentinel2.py
```

## Rollout

Phase 1:

- Implement reusable helper.
- Migrate Sentinel-2 only.
- Keep existing product-specific parsers.

Phase 2:

- Migrate MOD021KM, MODEV1F, MODND1D, and MODL1D.

Phase 3:

- Evaluate Landsat 8 migration after preserving cloud filtering and region-center sorting.
