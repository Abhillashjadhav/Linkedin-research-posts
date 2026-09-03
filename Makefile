PYTHON ?= python3

.PHONY: setup doctor privacy test check evals

setup:
	./bin/linkedin-os init

doctor:
	./bin/linkedin-os doctor

privacy:
	./bin/linkedin-os privacy-check

test: privacy
	PYTHONPATH=src PYTHONWARNINGS=error $(PYTHON) -m unittest discover -s tests -v

check: test

evals:
	cd evals/linkedin-os && \
	pm-verifier execute --project . --trials-out trials.executed.jsonl --results-out results.json -- $(PYTHON) adapter.py && \
	pm-verifier report --results results.json --out report.md
