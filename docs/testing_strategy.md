# Testing Strategy

This project separates tests into fast regression checks and slow integration checks.

## Fast regression

Run this after ordinary backend changes:

```powershell
.\scripts\test_fast.ps1
```

This executes:

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
```

## Slow integration tests

Run this before merging larger GIS, workflow, XGBoost, download, or result-presentation changes:

```powershell
.\scripts\test_slow.ps1
```

Slow tests include long-running workflow execution, model training, download postprocessing, and full presentation-result integration cases.

## Release candidate checks

Run this before controlled trial or release-candidate validation:

```powershell
.\scripts\test_release_candidate.ps1
```

To skip browser E2E during local diagnosis:

```powershell
.\scripts\test_release_candidate.ps1 -SkipBrowserE2E
```

## Marker policy

Use `@pytest.mark.slow` for tests that regularly take multiple seconds because they execute real GIS workflows, model training, download postprocessing, or browser-adjacent integration flows.

Do not mark security, encoding, session-isolation, or artifact-permission tests as slow unless they are genuinely expensive; those should remain in the fast regression set when possible.
