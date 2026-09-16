# Makefile
# Thin shim over the cross-platform task runner (poethepoet: `uv run poe <task>`)
# so the brief's `make <target>` interface works wherever GNU make exists.
# On Windows without make, run `uv run poe <task>` directly; the targets are
# identical. Later phases add: up, down, migrate, seed, dev, ingest-fjc,
# compute-metrics.
.PHONY: install test lint fmt typecheck check kit

install:
	uv sync

test:
	uv run poe test

lint:
	uv run poe lint

fmt:
	uv run poe fmt

typecheck:
	uv run poe typecheck

check:
	uv run poe check

kit:
	uv run poe kit
