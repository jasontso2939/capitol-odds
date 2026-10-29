.PHONY: setup fetch extract archive build site committees people insights report test all
setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fetch:
	bash scripts/fetch_raw.sh session
build:
	PYTHONPATH=src python3 -m calleg.build
test:
	PYTHONPATH=src python3 -m pytest -q
all: fetch extract archive build site committees people insights test
extract:
	bash scripts/extract_raw.sh
archive:  # earlier sessions (2007-08 to 2023-24; 1989-2005 are archived but not yet used), packed by .github/workflows/archive-sessions.yml
	git fetch --depth 1 origin session-archive && git archive FETCH_HEAD data/archive | tar x
site:
	PYTHONPATH=src python3 scripts/build_site.py
committees:
	PYTHONPATH=src python3 scripts/build_committees.py
people: committees
	PYTHONPATH=src python3 scripts/build_people.py
insights: committees
	PYTHONPATH=src python3 scripts/build_insights.py
report:  # what moved since the last commit (writes data/processed/headline.json)
	PYTHONPATH=src python3 scripts/change_report.py
