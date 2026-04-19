# Loblaw Bio Trial Dashboard

Repository: https://github.com/SiDdHaRtHrAjDaSh/Loblaw-Bio-Dashboard-Teiko

This project loads `cell-count.csv` into SQLite, runs a data pipeline to generate analysis artifacts, and serves the results in an interactive Flask dashboard.

## Repository Contents

- `load_data.py` — initializes the relational database schema and loads the raw CSV into SQLite.
- `pipeline.py` — computes summary tables, response statistics, baseline subset outputs, plots, and the report.
- `app.py` — Flask dashboard backend.
- `templates/index.html` — dashboard UI template.
- `static/styles.css` — dashboard styling.
- `requirements.txt` — Python dependencies.
- `Makefile` — automation targets used for setup, pipeline execution, and dashboard launch.
- `outputs/` — generated tables, plots, and report files.

## Run full project

To run all components with a single command use:

```bash
make dashboard
```

Creates the virtual environment and installs dependencies.
Runs the full data pipeline end-to-end.
Starts the local dashboard server.


## Required Makefile Targets

This repository includes the exact targets needed for grading:

- `make setup` — creates the virtual environment and installs dependencies.
- `make pipeline` — runs the full data pipeline end-to-end.
- `make dashboard` — starts the local dashboard server.

## Task mapping

- Part 1: `load_data.py` creates and populates `loblaw_bio_trial.db` using a normalized SQLite schema.
- Part 2: `pipeline.py` builds the relative frequency summary table (`outputs/summary_table.csv`) for each sample and population.
- Part 3: `pipeline.py` runs PBMC melanoma miraclib responder vs non-responder statistics, creates boxplots, and writes `outputs/response_stats.csv`.
- Part 4: `pipeline.py` queries baseline melanoma miraclib samples at time 0 for PBMC and WB, reports counts by project, response status, and sex, and includes an AI model note mentioning quintazide.

## Setup

Run the following commands in GitHub Codespaces or a local Linux/macOS shell:

```bash
python3 -m venv .venv
source .venv/bin/activate
make setup
```

On Windows PowerShell:

```powershell
python3 -m venv .venv
.\.venv\Scripts\Activate
make setup
```

## Run the pipeline

```bash
make pipeline
```

This command will:
1. create or refresh `loblaw_bio_trial.db`
2. load `cell-count.csv` into a normalized relational schema
3. generate output CSV files and plots in `outputs/`
4. create a human-readable report at `outputs/report.txt`

## Start the dashboard

```bash
make dashboard
```

Then open the dashboard at:

- `http://localhost:5000` for local development
- In GitHub Codespaces, forward port `5000` and open the forwarded URL

## Dashboard Link

The dashboard is accessible at `http://localhost:5000` once `make dashboard` is running.

## Database Schema

The relational schema is designed for a clinical trial hierarchy and scales naturally as the dataset grows.

### `projects`
Stores one row per project, with a stable `project_code`.

### `patients`
Stores one row per patient and links to `projects` via `project_id`.
Holds patient-level metadata such as `subject_code`, `age`, and `sex`.

### `samples`
Stores one row per biological sample/visit and links to `patients` via `patient_id`.
Includes sample-level metadata such as `condition`, `treatment`, `response`, `sample_type`, and `time_from_treatment_start`.

### `cell_counts`
Stores one row per `(sample_id, population)` measurement and links to `samples` via `sample_id`.
This avoids storing repeated sample or patient metadata for each population measurement.

### Design rationale and scalability

- The schema preserves the trial hierarchy explicitly: projects → patients → samples → cell_counts.
- It avoids duplicated metadata, which keeps storage efficient and improves update consistency.
- It scales well for hundreds of projects and thousands of samples because each table grows independently.
- Additional analytics are easy to support:
  - project-level aggregates by joining `projects` → `patients` → `samples`
  - patient-level longitudinal comparisons via `samples`
  - population-level analysis through `cell_counts`
  - support for new sample types or response definitions by adding columns or lookup tables without changing the core schema.

## Code Structure

- `load_data.py`: defines the normalized SQLite schema and loads `cell-count.csv` into it.
- `pipeline.py`: performs the analysis and writes outputs to `outputs/`.
  - summary table
  - response statistics
  - baseline subset tables
  - boxplot images
  - narrative report
- `app.py`: loads generated outputs and renders them in the dashboard.
  - exposes `/` for the dashboard
  - exposes `/outputs/<filename>` for download of generated CSV and report files
  - uses Jinja2 templates and Chart.js for interactive visualizations

### Why this design

- The separation of schema loading, analysis, and dashboard rendering keeps each stage focused and easy to maintain.
- The Makefile provides a reproducible grading interface.
- The dashboard consumes prepared outputs instead of recalculating expensive analytics on every request.
- The outputs folder makes it easy to inspect generated artifacts directly.

## Outputs

Generated outputs are stored in `outputs/` and include:

- `summary_table.csv`
- `response_stats.csv`
- `baseline_subset_pbmc.csv`
- `baseline_subset_wb.csv`
- `report.txt`
- PNG boxplots for each population

## Notes for Graders

- Use `make setup` once to install dependencies.
- Then run `make pipeline` to generate the data and outputs.
- Finally, run `make dashboard` and open port `5000` to view the dashboard.

## Current Status

This repository includes all required files: Python code, generated outputs, a working dashboard, and a Makefile with the exact requested targets.
