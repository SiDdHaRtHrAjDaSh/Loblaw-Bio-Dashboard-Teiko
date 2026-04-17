# Loblaw Bio Trial Dashboard

This project loads `cell-count.csv` into SQLite, runs the requested analysis, and serves all metrics in a local Flask dashboard.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make setup
```

On Windows PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate
```

## Run the full pipeline

```bash
make pipeline
```

This will:
1. create `loblaw_bio_trial.db`
2. load the CSV into a normalized relational schema
3. generate the summary table, response statistics, baseline subset, plot, and report in `outputs/`

## Start the dashboard

```bash
make dashboard
```

Then open:

http://localhost:5000

## Schema

The database uses the hierarchy:

`projects -> patients -> samples -> cell_counts`

### `projects`
One row per project, with a stable `project_code`.

### `patients`
One row per patient within a project. This stores patient-level information such as `subject_code`, `age`, and `sex`.

### `samples`
One row per biological sample / visit. This stores sample-level metadata such as `condition`, `treatment`, `response`, `sample_type`, and `time_from_treatment_start`.

### `cell_counts`
One row per `(sample, population)` pair, storing the count for each immune population.

This design keeps the trial hierarchy explicit and avoids duplicating project and patient metadata across multiple sample and population rows. It also scales well because the sample table can grow independently of the count table, and additional projects or patients can be added without changing the shape of the analysis code.

## Files

- `load_data.py`: creates the SQLite schema and loads `cell-count.csv`
- `pipeline.py`: computes summary metrics, statistics, subset outputs, and the plot
- `app.py`: Flask dashboard that renders the metrics in HTML
- `templates/index.html`: dashboard page template
- `requirements.txt`: Python dependencies
- `Makefile`: required automation entry points

## Answer

The dashboard displays the average B-cell count for melanoma male responders at time 0.
