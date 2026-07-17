PYTHON ?= python3

.PHONY: setup doctor privacy test check

setup:
	./bin/linkedin-os init

doctor:
	./bin/linkedin-os doctor

privacy:
	./bin/linkedin-os privacy-check

test: privacy
	PYTHONPATH=src PYTHONWARNINGS=error $(PYTHON) -m unittest discover -s tests -v

check: test
