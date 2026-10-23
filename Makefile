.PHONY: setup lint test demo validate research dashboard all

setup:
	uv sync --python 3.11

lint:
	uv run ruff check src tests scripts

test:
	uv run pytest -v

demo:
	uv run python scripts/generate_demo_data.py --output-dir artifacts/demo_data

validate:
	uv run python scripts/validate_dataset.py --input artifacts/demo_data/synthetic_mcx_gold.parquet

research:
	uv run python scripts/run_research.py --input artifacts/demo_data/synthetic_mcx_gold.parquet --output-dir artifacts/research_run

dashboard:
	uv run streamlit run scripts/launch_dashboard.py

all: lint test demo validate research
