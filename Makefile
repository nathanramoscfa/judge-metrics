# Makefile
# Thin shim over the cross-platform task runner (poethepoet: `uv run poe <task>`)
# so the brief's `make <target>` interface works wherever GNU make exists.
# On Windows without make, run `uv run poe <task>` directly; the targets are
# identical. Later steps add: dev-web, seed, compute-metrics, bootstrap.
.PHONY: install test lint fmt fmt-check typecheck check gate kit up down migrate dev-api ingest-fjc

install:
	uv sync

test:
	uv run poe test

lint:
	uv run poe lint

fmt:
	uv run poe fmt

fmt-check:
	uv run poe fmt-check

typecheck:
	uv run poe typecheck

check:
	uv run poe check

gate:
	uv run poe gate

kit:
	uv run poe kit

up:
	uv run poe up

down:
	uv run poe down

migrate:
	uv run poe migrate

dev-api:
	uv run poe dev-api

ingest-fjc:
	uv run poe ingest-fjc
