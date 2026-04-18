PYTHON ?= python3
VENV := .venv

ifeq ($(OS),Windows_NT)
PY := $(VENV)/Scripts/python
PIP := $(VENV)/Scripts/pip
FLASK := $(VENV)/Scripts/flask
else
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
FLASK := $(VENV)/bin/flask
endif

.PHONY: setup pipeline dashboard run all

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

pipeline:
	$(PY) load_data.py
	$(PY) pipeline.py

dashboard:
	$(FLASK) --app app run --host 0.0.0.0 --port 5000

run: setup pipeline dashboard

all: run