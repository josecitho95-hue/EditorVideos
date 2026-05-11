.PHONY: setup
setup: install-uv install-deps init-db init-qdrant
	@echo "✅ Setup completo. Corre 'make up' para servicios."

install-uv:
	@echo "Instalando uv..."
	@powershell -c "irm https://astral.sh/uv/install.ps1 | iex" || curl -LsSf https://astral.sh/uv/install.sh | sh

install-deps:
	uv sync --extra dev

init-db:
	uv run autoedit db migrate

init-qdrant:
	uv run python infra/qdrant_init.py

up:
	docker compose up -d redis qdrant

down:
	docker compose down

worker:
	uv run autoedit worker run

dashboard:
	uv run autoedit dashboard

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

fmt:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

typecheck:
	uv run mypy src/ tests/

ci: lint typecheck test
