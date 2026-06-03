# Agent Hardening Design

## Scope

This upgrade hardens the existing GIS agent for real user operation without replacing its architecture. It covers documentation, CI, GSCloud download reliability, commercial quota safety, task cancellation/retry, product startup deduplication, and frontend task actions.

## Backend Behavior

Platform-account download jobs reserve quota when accepted. Failed, canceled, or waiting-login jobs release that reservation. Completed jobs mark the reservation as charged and do not double-count. Running and waiting jobs cannot be deleted directly; users cancel them first so the service can release quota and preserve an audit trail.

Retry creates a new job with the original source, product, region, dates, account mode, request text, direct URL, local file, and output name. The new job stores `retried_from_job_id`.

## GSCloud Reliability

The scene product registry records supported GSCloud products in one place. Scene process startup is centralized in `start_gscloud_scene_process`, while existing product-specific functions remain as compatibility wrappers.

Download validation now includes file-level checks and a map-ready artifact validation helper for GeoJSON and raster outputs.

## Frontend

Download task cards show reserved quota and retry source. Active jobs expose cancel, retryable jobs expose retry, and deletion is disabled until the task is in a terminal state.

## Repository Operations

The root README documents setup, secrets, GSCloud login state, tests, and job safety. CI runs Python tests and frontend build/checks on push and pull requests. A manual GSCloud preflight workflow can validate the live source when a storage-state secret is configured.

## Testing

Unit tests cover quota reservation/release, cancellation, retry cloning, deletion safety, product registry coverage, and GIS artifact bounds validation. Existing Python and frontend tests remain part of the regression suite.
