.PHONY: backend-test backend-lint frontend-install frontend-test frontend-lint frontend-build test lint build

backend-test:
	cd backend && uv run --extra dev pytest -v

backend-lint:
	cd backend && uv run --extra dev ruff check .
	cd backend && uv run --extra dev ruff format --check .

frontend-install:
	cd frontend && npm install

frontend-test:
	cd frontend && npm run test

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

test: backend-test frontend-test

lint: backend-lint frontend-lint

build: frontend-build
