"""Generate a read-only JSON audit of the repository structure."""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PYTHON_ROOTS = ("api", "core", "domain", "infrastructure", "services", "scripts")
FRONTEND_ROOT = Path("ui_next/src")
RUNTIME_ROOTS = ("workspace", "artifacts", "secrets", "local_library")
MARKER_PATTERN = re.compile(r"\b(?:TODO|FIXME|deprecated|legacy)\b", re.IGNORECASE)
IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:type\s+)?(?:.+?\s+from\s+)?[\"']([^\"']+)[\"']", re.MULTILINE)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_python_files(root: Path) -> list[Path]:
    files = [root / "api_server.py", root / "app.py"]
    for directory in PYTHON_ROOTS:
        base = root / directory
        if base.exists():
            files.extend(base.rglob("*.py"))
    return sorted({path for path in files if path.is_file()})


def _directory_stats(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"files": 0, "bytes": 0}
    files = [child for child in path.rglob("*") if child.is_file()]
    size = 0
    for child in files:
        try:
            size += child.stat().st_size
        except OSError:
            continue
    return {"files": len(files), "bytes": size}


def build_audit(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    python_imports: list[dict[str, str]] = []
    routes: list[dict[str, str]] = []
    functions: dict[str, list[str]] = defaultdict(list)
    markers: list[dict[str, Any]] = []
    large_files: list[dict[str, Any]] = []

    for path in _iter_python_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        relative = _relative(path, root)
        lines = source.splitlines()
        if len(lines) >= 300:
            large_files.append({"path": relative, "lines": len(lines)})
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            markers.append({"path": relative, "line": exc.lineno or 0, "text": "syntax_error"})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    python_imports.append({"source": relative, "target": alias.name})
            elif isinstance(node, ast.ImportFrom):
                python_imports.append({"source": relative, "target": node.module or ""})
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name].append(f"{relative}:{node.lineno}")
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                        continue
                    if decorator.func.attr.lower() not in {"get", "post", "put", "patch", "delete"}:
                        continue
                    if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                        continue
                    routes.append(
                        {
                            "method": decorator.func.attr.upper(),
                            "path": str(decorator.args[0].value),
                            "module": relative,
                            "handler": node.name,
                        }
                    )
        for line_number, line in enumerate(lines, start=1):
            if MARKER_PATTERN.search(line):
                markers.append({"path": relative, "line": line_number, "text": line.strip()[:240]})

    frontend_imports: list[dict[str, str]] = []
    frontend_base = root / FRONTEND_ROOT
    if frontend_base.exists():
        for path in sorted([*frontend_base.rglob("*.ts"), *frontend_base.rglob("*.tsx")]):
            source = path.read_text(encoding="utf-8", errors="replace")
            relative = _relative(path, root)
            lines = source.splitlines()
            if len(lines) >= 300:
                large_files.append({"path": relative, "lines": len(lines)})
            frontend_imports.extend({"source": relative, "target": target} for target in IMPORT_PATTERN.findall(source))
            for line_number, line in enumerate(lines, start=1):
                if MARKER_PATTERN.search(line):
                    markers.append({"path": relative, "line": line_number, "text": line.strip()[:240]})

    duplicate_functions = {
        name: locations
        for name, locations in sorted(functions.items())
        if len(locations) > 1
    }
    route_counts = Counter((route["method"], route["path"]) for route in routes)
    duplicate_routes = [
        {"method": method, "path": path, "count": count}
        for (method, path), count in sorted(route_counts.items())
        if count > 1
    ]
    runtime = {name: _directory_stats(root / name) for name in RUNTIME_ROOTS}

    return {
        "project_root": str(root),
        "python_imports": python_imports,
        "api_routes": routes,
        "duplicate_api_routes": duplicate_routes,
        "duplicate_python_functions": duplicate_functions,
        "frontend_imports": frontend_imports,
        "large_files": sorted(large_files, key=lambda item: (-item["lines"], item["path"])),
        "markers": markers,
        "runtime": runtime,
    }


def write_audit(project_root: Path, output_path: Path) -> Path:
    output = output_path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_audit(project_root), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(write_audit(args.project_root, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
