.PHONY: setup fetch extract build site test all
setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fetch:
	bash scripts/fetch_raw.sh session
build:
	PYTHONPATH=src python3 -m calleg.build
test:
	PYTHONPATH=src python3 -m pytest -q
all: fetch extract build site test
extract:
	bash scripts/extract_raw.sh
site:
	PYTHONPATH=src python3 scripts/build_site.py
