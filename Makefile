PYTHON ?= python3

.PHONY: setup doctor test

setup:
	./bin/linkedin-os init

doctor:
	./bin/linkedin-os doctor

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
