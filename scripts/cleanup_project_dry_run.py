"""Print the approved GIS Agent cleanup migration plan without changing files."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import NamedTuple


DEFAULT_ARCHIVE_ROOT = Path(r"E:\agent\test")


class PlanItem(NamedTuple):
    category: str
    source: Path
    destination: Path | None
    reason: str
    evidence: str
    move: bool
    sensitive: bool = False


def _item(
    category: str,
    source: str,
    destination_root: Path,
    reason: str,
    evidence: str,
    *,
    move: bool,
    sensitive: bool = False,
) -> PlanItem:
    relative = Path(source)
    return PlanItem(
        category=category,
        source=relative,
        destination=destination_root / relative if move else None,
        reason=reason,
        evidence=evidence,
        move=move,
        sensitive=sensitive,
    )


def build_plan(project_root: Path, destination_root: Path) -> list[PlanItem]:
    """Return the decision-complete path plan; do not inspect file contents."""
    keep = [
        (".git", "Git repository metadata; moving it would break repository identity."),
        (".github", "Active CI workflows for Python, frontend, and smoke verification."),
        (".env", "Real runtime configuration explicitly retained; content is never printed."),
        (".env.example", "Required environment configuration documentation."),
        (".gitignore", "Repository hygiene rules."),
        (".venv", "Current GIS Python environment retained for reproducible verification."),
        ("README.md", "Current FastAPI and React setup/run documentation."),
        ("requirements.txt", "Python dependency manifest; Streamlit line will be removed only after confirmation."),
        ("api_server.py", "Active FastAPI backend imported by tests, CI, and launchers."),
        ("app.py", "Backend launcher used by start_backend_api.ps1."),
        ("start_backend_api.ps1", "Supported backend startup script."),
        ("start_web_ui.ps1", "Supported frontend startup script."),
        ("core", "Backend agent, tools, workflows, storage, conversation, and download implementation."),
        ("tests", "Python regression tests and small fixtures."),
        ("scripts", "Operational diagnostics, health checks, smoke tests, and this dry-run tool."),
        ("ui_next/package.json", "Frontend scripts and dependency manifest."),
        ("ui_next/package-lock.json", "Frontend reproducible dependency lock."),
        ("ui_next/src", "Active React application source."),
        ("ui_next/tests", "Frontend unit tests, including uncommitted hover stability coverage."),
        ("ui_next/e2e", "Playwright core workflow tests."),
        ("ui_next/public", "Referenced frontend static assets."),
        ("ui_next/index.html", "Vite HTML entrypoint."),
        ("ui_next/vite.config.ts", "Vite build, proxy, and chunk configuration."),
        ("ui_next/tsconfig.json", "TypeScript compiler configuration."),
        ("ui_next/playwright.config.ts", "Frontend Playwright configuration."),
        ("ui_next/playwright.real-backend.config.ts", "Real-backend Playwright configuration."),
        ("ui_next/postcss.config.js", "Frontend CSS build configuration."),
        ("ui_next/tailwind.config.ts", "Frontend styling configuration."),
        ("workspace/local_library", "Active built-in GIS library selected by GIS_AGENT_LOCAL_LIBRARY_DIR."),
    ]
    items = [
        _item("A", path, destination_root, reason, "Active entrypoint, reference, test, or approved runtime dependency.", move=False)
        for path, reason in keep
    ]

    movable = [
        ("web_app.py", "Legacy Streamlit UI; current README, launchers, CI, and frontend use FastAPI + React.", "Only self-contained Streamlit imports remain."),
        (".streamlit", "Configuration used only by the legacy Streamlit UI.", "No active launcher or CI reference."),
        ("package-lock.json", "Empty root npm lockfile; the active frontend lock is ui_next/package-lock.json.", "Root lock contains no packages."),
        ("docs/superpowers/specs", "Historical implementation design records, not runtime documentation.", "No runtime or test imports."),
        (".vscode", "Developer-local IDE configuration.", "Ignored and not required by runtime."),
        ("output", "Empty or generated output directory outside the supported workspace model.", "Ignored/generated content."),
        ("__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("core/__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("core/commercial/__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("core/domestic_sources/__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("scripts/__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("tests/__pycache__", "Generated Python bytecode cache.", "Recreated automatically."),
        ("ui_next/node_modules", "Reproducible frontend dependencies; rebuild with npm ci.", "Generated from ui_next/package-lock.json."),
        ("ui_next/dist", "Frontend build output.", "Recreated by npm run build."),
        ("ui_next/test-results", "Playwright generated test output.", "Not required by runtime."),
        ("ui_next/tsconfig.tsbuildinfo", "TypeScript incremental build cache.", "Recreated by TypeScript."),
        ("ui_next/vite-dev.out.log", "Development server log.", "Historical log output."),
        ("ui_next/vite-dev.err.log", "Development server error log.", "Historical log output."),
    ]
    items.extend(
        _item("B", path, destination_root, reason, evidence, move=True)
        for path, reason, evidence in movable
    )

    sensitive = [
        ("secrets", "Browser login state and authentication material."),
        ("workspace/anonymous", "Anonymous conversations, uploads, derived results, and artifacts."),
        ("workspace/users", "User conversations, uploads, derived results, and artifacts."),
        ("workspace/commercial.db", "Accounts, subscriptions, quotas, credentials, and job records."),
        ("workspace/workspace.db", "Workspace catalog, conversations, messages, and artifacts."),
        ("workspace/commercial_secret.key", "Encryption key for stored commercial credentials."),
        ("workspace/domestic_auth", "Saved browser sessions, cookies, and download job state."),
        ("workspace/domestic_downloads", "Historical downloaded GIS products."),
        ("workspace/derived", "Historical generated GIS and model artifacts."),
        ("workspace/gscloud_download_verification", "Historical GSCloud verification download."),
        ("workspace/verification", "Historical verification outputs."),
        ("workspace/uploads", "Historical root workspace uploads."),
        ("workspace/plots", "Historical generated plots."),
        ("workspace/temp", "Historical temporary files."),
        ("workspace/exports", "Historical export artifacts."),
        ("workspace/demo_xgboost_soil_moisture.csv", "Runtime demo data outside the retained built-in library."),
    ]
    items.extend(
        _item(
            "C",
            path,
            destination_root,
            reason,
            "Complete runtime reset approved; content must never be printed.",
            move=True,
            sensitive=True,
        )
        for path, reason in sensitive
    )

    unsure = [
        ("local_library", "Duplicate library data exists, but its manifest and README differ from the active workspace copy."),
        ("ui_next/src/components/ErrorBoundary.tsx", "No current import found, but it is a plausible application safety component."),
    ]
    items.extend(
        _item("D", path, destination_root, reason, "Insufficient evidence for safe removal.", move=False)
        for path, reason in unsure
    )
    return items


def _resolved_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return False


def _safe_relative_child(path: Path, project_root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(project_root.resolve(strict=False))
        return path.absolute().relative_to(project_root.absolute())
    except ValueError:
        return None


def _size_and_files(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if _is_link_like(path):
        return 0, 0
    if path.is_file():
        return path.stat().st_size, 1
    total = 0
    count = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def print_plan(project_root: Path, destination_root: Path) -> int:
    project_root = project_root.resolve()
    destination_root = destination_root.resolve(strict=False)
    items = build_plan(project_root, destination_root)
    problems: list[str] = []

    print("DRY RUN ONLY - no files will be moved, deleted, edited, or created")
    print(f"Project root: {project_root}")
    print(f"Proposed batch destination: {destination_root}")
    print("Sensitive entries show paths and metadata only; file contents are never read.")

    if _resolved_under(destination_root, project_root):
        problems.append("archive destination must not be inside the project root")
    if destination_root.exists():
        problems.append("batch destination already exists; execution must use a new timestamp")

    for category in ("A", "B", "C", "D"):
        print(f"\n[{category}]")
        for item in (entry for entry in items if entry.category == category):
            source = project_root / item.source
            if not _is_link_like(source) and not _resolved_under(source, project_root):
                problems.append(f"source escapes project root: {item.source}")
            size, files = _size_and_files(source)
            target = str(item.destination) if item.destination else "KEEP IN PLACE"
            state = "MOVE" if item.move else "KEEP"
            exists = source.exists()
            print(f"- {state} {item.source} -> {target}")
            print(f"  exists={exists} files={files} size={_format_size(size)} sensitive={item.sensitive}")
            print(f"  reason={item.reason}")
            print(f"  evidence={item.evidence}")
            if item.move and exists and item.destination and item.destination.exists():
                problems.append(f"target collision: {item.destination}")
            if item.move and _is_link_like(source):
                print(f"  linked-directory={item.source} traversal=skipped")
            elif item.move and source.is_dir():
                for child in sorted(path for path in source.rglob("*") if path.is_file()):
                    relative = _safe_relative_child(child, project_root)
                    if relative is None:
                        print("  linked-child traversal=skipped")
                        continue
                    child_size = child.stat().st_size
                    label = "sensitive-file" if item.sensitive else "move-file"
                    print(f"  {label}={relative} size={_format_size(child_size)}")

    print("\n[POST-CONFIRMATION EDIT]")
    print("- Back up requirements.txt into the batch directory, then remove only streamlit>=1.55.0.")
    print("- Rebuild ui_next/node_modules with npm ci after migration.")
    print("- D items remain in place.")

    print("\n[SAFETY CHECKS]")
    if problems:
        for problem in problems:
            print(f"- BLOCKED: {problem}")
        return 2
    print("- PASS: destination is outside the project and does not yet exist")
    print("- PASS: no proposed source escapes the project root")
    print("- PASS: no existing destination collisions found")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    destination = args.archive_root / args.project_root.resolve().name / args.timestamp
    return print_plan(args.project_root, destination)


if __name__ == "__main__":
    raise SystemExit(main())
