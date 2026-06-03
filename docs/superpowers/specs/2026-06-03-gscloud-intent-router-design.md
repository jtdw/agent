# GSCloud Intent Router Design

## Goal

Improve the GIS agent's ability to understand imperfect user requests for existing GSCloud download products. Users may use aliases, shorthand, Chinese descriptions, partial product names, or common typos. The router should map these requests to existing deterministic download flows when confidence is high, ask a focused clarification when confidence is medium, and fall back to the normal chat path when confidence is low.

## Scope

This first phase covers intent recognition only. It does not change the browser downloaders, pagination strategy, AOI filtering, account management, frontend UI, or workspace import behavior.

Covered product intents:

- GSCloud DEM
- Landsat 8 OLI_TIRS
- Sentinel-2
- MODND1D China 500M NDVI daily
- MODL1D China 1KM land surface temperature daily
- MODEV1F China 250M EVI 5-day composite
- MOD021KM 1KM surface reflectance

## Architecture

Add a small module at `core/domestic_sources/intent_router.py`.

The module exposes a single primary function:

```python
route_gscloud_download_intent(prompt: str) -> GSCloudIntentRoute
```

`GSCloudIntentRoute` will include:

- `kind`: `matched`, `clarify`, or `none`
- `product_key`: selected product key when available
- `resource_type`: existing commercial job resource type when available
- `confidence`: numeric score from 0.0 to 1.0
- `matched_terms`: terms that contributed to the score
- `clarification`: short Chinese clarification text for ambiguous requests

## Matching Behavior

The router will combine these signals:

- Existing exact aliases from `gscloud_products.py`
- Normalized aliases without spaces, hyphens, and punctuation
- Simple typo tolerance using Python standard library similarity scoring
- Intent category words such as vegetation, NDVI, EVI, elevation, DEM, reflectance, temperature, Sentinel, Landsat, remote sensing image
- Download action words such as download, get, prepare, retrieve, 下载, 获取, 准备, 检索

High-confidence examples should directly route:

- `下载 sentinal2 数据` -> Sentinel-2
- `帮我获取哨兵二L2A影像` -> Sentinel-2
- `下载 mod21km 地表反射` -> MOD021KM
- `下载五天evi` -> MODEV1F
- `获取地表温度` -> MODL1D

Medium-confidence examples should ask a clarification:

- `下载植被数据` -> ask user to choose NDVI or EVI
- `下载遥感影像` -> ask user to choose Sentinel-2 or Landsat 8
- `下载MODIS数据` -> ask user to choose NDVI, LST, EVI, or MOD021KM

Low-confidence examples should not create jobs.

## API Integration

In `api_server.py`, call the new router before the current sequence of `_is_gscloud_*_download_prompt()` checks.

If `kind == matched`, dispatch to the existing submit function for that product.

If `kind == clarify`, save the user message and return the clarification reply without creating a job.

If `kind == none`, continue to the existing route sequence and then the normal LLM path.

## Error Handling

The router must not start downloads by itself. It only returns a route decision.

If a high-confidence route maps to a product whose worker is unavailable, the existing product-specific submit function remains responsible for the user-facing error.

Clarification replies must be concrete and short, for example:

`你是想下载 NDVI 还是 EVI？如果用于植被指数时间序列，通常选 NDVI；如果需要 250M 五天合成增强植被指数，选 EVI。`

## Testing

Add tests for:

- Exact product aliases still match.
- Common typo examples route correctly.
- Ambiguous vegetation and remote-sensing requests return clarification, not jobs.
- Low-confidence prompts return `none`.
- Existing product tests continue to pass.

Run:

```powershell
python -m unittest discover tests
python -m py_compile api_server.py core\domestic_sources\intent_router.py core\domestic_sources\gscloud_products.py
```

## Non-Goals

- No full-pagination scanner changes.
- No AOI/geometry filtering changes.
- No frontend changes.
- No LLM prompt redesign.
- No account or payment changes.
