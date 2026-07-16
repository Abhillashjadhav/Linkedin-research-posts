PYTHON ?= python3

.PHONY: setup doctor test privacy

setup:
	$(PYTHON) -m venv .venv
	./bin/linkedin-os init

doctor:
	./bin/linkedin-os doctor

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

privacy:
	$(PYTHON) scripts/check_privacy.py
