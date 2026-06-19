from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class GSCloudDirectDownloadRoute:
    product_key: str
    matches: Callable[[str], bool]
    submit: Callable[..., dict[str, Any]]
    result_meta_keys: tuple[str, ...]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def _route_value(route: Any, key: str, default: Any = None) -> Any:
    if isinstance(route, Mapping):
        return route.get(key, default)
    return getattr(route, key, default)


def validate_unique_product_keys(routes: Iterable[Any]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for route in routes:
        key = str(_route_value(route, "product_key") or "").strip()
        if not key:
            raise ValueError("GSCloud route product_key cannot be empty")
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        raise ValueError(f"Duplicate GSCloud product_key values: {', '.join(sorted(duplicates))}")


def match_direct_download_route(
    routes: Iterable[Any],
    prompt: str,
) -> Any | None:
    for route in routes:
        matches = _route_value(route, "matches")
        if callable(matches) and matches(prompt):
            return route
    return None


def route_by_product_key(
    routes: Iterable[Any],
    product_key: str,
) -> Any | None:
    target = str(product_key or "").strip()
    if not target:
        return None
    for route in routes:
        if str(_route_value(route, "product_key") or "").strip() == target:
            return route
    return None
