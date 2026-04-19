from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, send_from_directory, url_for

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
STATIC_DIR = ROOT / "static"

POPULATIONS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(STATIC_DIR),
)

TABLE_SPECS = {
    "summary": {
        "filename": "summary_table.csv",
        "title": "Summary table",
        "preview_limit": 10,
    },
    "stats": {
        "filename": "response_stats.csv",
        "title": "Statistics table",
        "preview_limit": 5,
    },
    "subset": {
        "filename": "baseline_subset.csv",
        "title": "Baseline subset",
        "preview_limit": 10,
    },
}


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def _prepare_table(df: pd.DataFrame, limit: int | None = None) -> tuple[list[str], list[dict]]:
    """
    Add a visible row number column and return columns + rows.
    If limit is provided, only the first `limit` rows are returned.
    """
    if df.empty:
        return [], []

    out = df.copy().reset_index(drop=True)
    out.insert(0, "row", range(1, len(out) + 1))

    if limit is not None:
        out = out.head(limit)

    out = out.where(pd.notna(out), None)
    return list(out.columns), out.to_dict(orient="records")


def _load_table_from_disk(table_name: str) -> pd.DataFrame:
    spec = TABLE_SPECS.get(table_name)
    if spec is not None:
        return _read_csv_if_exists(OUTPUTS / spec["filename"])
    elif table_name.startswith("subset_"):
        # Handle subset tables for different sample types
        sample_type = table_name.split("_", 1)[1].upper()
        filename = f"baseline_subset_{sample_type.lower()}.csv"
        return _read_csv_if_exists(OUTPUTS / filename)
    else:
        raise KeyError(table_name)


def load_page_data() -> dict:
    summary_df = _load_table_from_disk("summary")
    stats_df = _load_table_from_disk("stats")
    
    # Load subset data for different sample types
    subset_dfs = {}
    sample_types = ['PBMC', 'WB']
    for sample_type in sample_types:
        filename = f"baseline_subset_{sample_type.lower()}.csv"
        if (OUTPUTS / filename).exists():
            subset_dfs[sample_type] = pd.read_csv(OUTPUTS / filename)
        else:
            subset_dfs[sample_type] = pd.DataFrame()

    report_path = OUTPUTS / "report.txt"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_sections = []
    if report_text:
        for section in [s.strip() for s in report_text.split("\n\n") if s.strip()]:
            lines = section.splitlines()
            report_sections.append({
                "title": lines[0],
                "body": lines[1:] if len(lines) > 1 else [],
            })

    answer = None
    if report_text:
        for line in report_text.splitlines():
            if line.startswith("Average B cells for melanoma male responders at time=0"):
                answer = line.split(":", 1)[1].strip()
                break

    summary_columns, summary_preview = _prepare_table(summary_df, TABLE_SPECS["summary"]["preview_limit"])
    stats_columns, stats_preview = _prepare_table(stats_df, TABLE_SPECS["stats"]["preview_limit"])
    
    # Create table configs for each subset
    subset_table_configs = {}
    for sample_type, df in subset_dfs.items():
        columns, preview = _prepare_table(df, 10)  # Preview limit of 10
        subset_table_configs[sample_type] = {
            "title": f"Baseline subset - {sample_type}",
            "endpoint": f"/api/table/subset_{sample_type.lower()}",
            "columns": columns,
            "preview_rows": preview,
            "preview_limit": 10,
        }

    # Prepare chart data for stats
    chart_data = {
        "labels": stats_df["population"].tolist() if not stats_df.empty else [],
        "responders": stats_df["responders_mean_pct"].tolist() if not stats_df.empty else [],
        "non_responders": stats_df["non_responders_mean_pct"].tolist() if not stats_df.empty else [],
    }

    # Prepare gauge data for response rates
    gauge_data = []
    if not stats_df.empty:
        for _, row in stats_df.iterrows():
            responders = int(row["n_responders"])
            non_responders = int(row["n_non_responders"])
            total = responders + non_responders
            percent = float((responders / total) * 100) if total > 0 else 0.0
            gauge_data.append({
                "population": row["population"],
                "responders": responders,
                "non_responders": non_responders,
                "percent_responders": percent,
            })

    schema = [
        {
            "name": "projects",
            "title": "projects",
            "columns": ["project_id PK", "project_code"],
            "note": "One row per project.",
        },
        {
            "name": "patients",
            "title": "patients",
            "columns": ["patient_id PK", "project_id FK", "subject_code", "age", "sex"],
            "note": "One row per patient within a project.",
            "fk": "projects.project_id → patients.project_id",
        },
        {
            "name": "samples",
            "title": "samples",
            "columns": [
                "sample_id PK",
                "patient_id FK",
                "condition",
                "treatment",
                "response",
                "sample_type",
                "time_from_treatment_start",
            ],
            "note": "One row per biological sample/visit.",
            "fk": "patients.patient_id → samples.patient_id",
        },
        {
            "name": "cell_counts",
            "title": "cell_counts",
            "columns": ["cell_count_id PK", "sample_id FK", "population", "count"],
            "note": "One row per sample-population measurement.",
            "fk": "samples.sample_id → cell_counts.sample_id",
        },
    ]

    relationships = [
        "projects.project_id → patients.project_id",
        "patients.patient_id → samples.patient_id",
        "samples.sample_id → cell_counts.sample_id",
    ]

    total_rows = len(summary_df)
    unique_samples = summary_df["sample"].nunique() if not summary_df.empty and "sample" in summary_df.columns else 0

    project_story = [
    {
        "title": "1. Problem Decomposition into a Relational Schema",
        "text": "The dataset is modeled as projects → patients → samples → cell_counts, ensuring that project-level, patient-level, and sample-level information remain distinct, normalized, and easily queryable.",
    },
    {
        "title": "2. SQLite Data Loading Pipeline",
        "text": "A data loading script (load_data.py) reconstructs the database from scratch, inserts records into appropriate tables, and maintains referential integrity through foreign-key relationships.",
    },
    {
        "title": "3. Data Integrity and Lossless Verification",
        "text": "The original dataset is reconstructed from the normalized tables and compared against the source CSV to confirm that no data is lost or altered during the transformation process.",
    },
    {
        "title": "4. Analytical Pipeline Execution",
        "text": "The pipeline computes per-sample relative frequencies, performs statistical comparisons between responders and non-responders, and extracts baseline melanoma PBMC subsets at time 0 for targeted analysis.",
    },
    {
        "title": "5. Interactive Dashboard Development",
        "text": "A Flask-based dashboard presents the results, including schema visualization, scrollable data tables with preview/full toggles, and consolidated outputs for intuitive exploration in a single local interface.",
    },
]

    table_config = {
        "summary": {
            "title": TABLE_SPECS["summary"]["title"],
            "endpoint": "/api/table/summary",
            "download_url": url_for("outputs", filename=TABLE_SPECS["summary"]["filename"]),
            "columns": summary_columns,
            "preview_rows": summary_preview,
            "preview_limit": TABLE_SPECS["summary"]["preview_limit"],
        },
        "stats": {
            "title": TABLE_SPECS["stats"]["title"],
            "endpoint": "/api/table/stats",
            "download_url": url_for("outputs", filename=TABLE_SPECS["stats"]["filename"]),
            "columns": stats_columns,
            "preview_rows": stats_preview,
            "preview_limit": TABLE_SPECS["stats"]["preview_limit"],
        },
    }
    
    # Add subset configs for each sample type
    for sample_type, config in subset_table_configs.items():
        config["download_url"] = url_for("outputs", filename=f"baseline_subset_{sample_type.lower()}.csv")
        table_config[f"subset_{sample_type.lower()}"] = config

    return {
        "answer": answer,
        "report_text": report_text,
        "report_sections": report_sections,
        "report_download_url": url_for("outputs", filename="report.txt") if report_path.exists() else None,
        "schema": schema,
        "relationships": relationships,
        "table_config": table_config,
        "available_plots": [pop for pop in POPULATIONS if (STATIC_DIR / f"{pop}_boxplot.png").exists()],
        "total_rows": total_rows,
        "unique_samples": unique_samples,
        "project_story": project_story,
        "chart_data": chart_data,
        "gauge_data": gauge_data,
    }


@app.route("/")
def index():
    return render_template("index.html", **load_page_data())


@app.route("/api/table/<table_name>")
def api_table(table_name: str):
    try:
        df = _load_table_from_disk(table_name)
        columns, rows = _prepare_table(df, None)
        return jsonify({"columns": columns, "rows": rows})
    except KeyError:
        return jsonify({"error": "Unknown table"}), 404


@app.route("/outputs/<path:filename>")
def outputs(filename: str):
    return send_from_directory(OUTPUTS, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)