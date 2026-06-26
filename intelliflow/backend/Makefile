.PHONY: install ingest run test eval

install:
	pip install -e ".[dev]"

ingest:
	python -m app.rag.ingest

run:
	uvicorn app.main:app --reload

test:
	pytest -v

eval:
	python -m app.rag.eval.eval
