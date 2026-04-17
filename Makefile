PYTHON ?= python3
VENV := .venv
ifeq ($(OS),Windows_NT)
PY := $(VENV)/Scripts/python
PIP := $(VENV)/Scripts/pip
FLASK := $(VENV)/Scripts/flask
ACTIVATE := $(VENV)/Scripts/Activate
else
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
FLASK := $(VENV)/bin/flask
ACTIVATE := source $(VENV)/bin/activate
endif

.PHONY: setup pipeline dashboard

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

pipeline:
	$(PY) load_data.py
	$(PY) pipeline.py

dashboard:
	$(FLASK) --app app run --host 0.0.0.0 --port 5000
