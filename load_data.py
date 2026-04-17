"""Load cell-count.csv into a normalized SQLite database.

Schema:
    projects -> patients -> samples -> cell_counts

This loader always rebuilds the database from scratch so it is safe to rerun
when the schema changes or an old .db file already exists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "cell-count.csv"
DB_PATH = ROOT / "loblaw_bio_trial.db"
POPULATION_COLUMNS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Drop any existing tables and create the relational schema fresh."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(
        """
        DROP TABLE IF EXISTS cell_counts;
        DROP TABLE IF EXISTS samples;
        DROP TABLE IF EXISTS patients;
        DROP TABLE IF EXISTS projects;

        CREATE TABLE projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_code TEXT NOT NULL UNIQUE
        );

        CREATE TABLE patients (
            patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            subject_code TEXT NOT NULL,
            age INTEGER,
            sex TEXT,
            UNIQUE (project_id, subject_code),
            FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );

        CREATE TABLE samples (
            sample_id TEXT PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            condition TEXT NOT NULL,
            treatment TEXT NOT NULL,
            response TEXT NOT NULL,
            sample_type TEXT NOT NULL,
            time_from_treatment_start INTEGER NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
        );

        CREATE TABLE cell_counts (
            cell_count_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT NOT NULL,
            population TEXT NOT NULL,
            count INTEGER NOT NULL,
            UNIQUE (sample_id, population),
            FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE,
            CHECK (population IN ('b_cell', 'cd8_t_cell', 'cd4_t_cell', 'nk_cell', 'monocyte'))
        );

        CREATE INDEX idx_patients_project_id
            ON patients (project_id);
        CREATE INDEX idx_patients_subject_code
            ON patients (subject_code);
        CREATE INDEX idx_samples_patient_id
            ON samples (patient_id);
        CREATE INDEX idx_samples_condition_treatment_response_time
            ON samples (condition, treatment, response, time_from_treatment_start);
        CREATE INDEX idx_samples_sample_type
            ON samples (sample_type);
        CREATE INDEX idx_cell_counts_sample_id
            ON cell_counts (sample_id);
        CREATE INDEX idx_cell_counts_population
            ON cell_counts (population);
        """
    )


def _validate_columns(df: pd.DataFrame) -> None:
    required = {
        "project",
        "subject",
        "condition",
        "age",
        "sex",
        "treatment",
        "response",
        "sample",
        "sample_type",
        "time_from_treatment_start",
        *POPULATION_COLUMNS,
    }
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")


def _load_projects(df: pd.DataFrame, conn: sqlite3.Connection) -> Dict[str, int]:
    project_codes = sorted(df["project"].dropna().astype(str).unique())
    conn.executemany(
        "INSERT INTO projects (project_code) VALUES (?)",
        [(project_code,) for project_code in project_codes],
    )
    rows = conn.execute("SELECT project_id, project_code FROM projects").fetchall()
    return {row[1]: row[0] for row in rows}


def _load_patients(
    df: pd.DataFrame, conn: sqlite3.Connection, project_id_map: Dict[str, int]
) -> Dict[Tuple[str, str], int]:
    patient_rows = (
        df[["project", "subject", "age", "sex"]]
        .drop_duplicates(subset=["project", "subject"])
        .sort_values(["project", "subject"])
    )
    payload = [
        (
            project_id_map[str(row.project)],
            str(row.subject),
            None if pd.isna(row.age) else int(row.age),
            None if pd.isna(row.sex) else str(row.sex),
        )
        for row in patient_rows.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT INTO patients (project_id, subject_code, age, sex) VALUES (?, ?, ?, ?)",
        payload,
    )
    rows = conn.execute(
        "SELECT p.patient_id, pr.project_code, p.subject_code FROM patients p JOIN projects pr ON pr.project_id = p.project_id"
    ).fetchall()
    return {(row[1], row[2]): row[0] for row in rows}


def _load_samples(
    df: pd.DataFrame, conn: sqlite3.Connection, patient_id_map: Dict[Tuple[str, str], int]
) -> None:
    sample_rows = (
        df[
            [
                "project",
                "subject",
                "sample",
                "condition",
                "treatment",
                "response",
                "sample_type",
                "time_from_treatment_start",
            ]
        ]
        .drop_duplicates(subset=["sample"])
        .sort_values("sample")
    )
    payload = [
        (
            str(row.sample),
            patient_id_map[(str(row.project), str(row.subject))],
            str(row.condition),
            str(row.treatment),
            str(row.response),
            str(row.sample_type),
            int(row.time_from_treatment_start),
        )
        for row in sample_rows.itertuples(index=False)
    ]
    conn.executemany(
        """
        INSERT INTO samples (
            sample_id, patient_id, condition, treatment, response, sample_type, time_from_treatment_start
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )


def _load_cell_counts(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    long_counts = (
        df[["sample", *POPULATION_COLUMNS]]
        .melt(id_vars="sample", var_name="population", value_name="count")
        .rename(columns={"sample": "sample_id"})
        .sort_values(["sample_id", "population"])
    )
    payload = [
        (str(row.sample_id), str(row.population), int(row.count))
        for row in long_counts.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT INTO cell_counts (sample_id, population, count) VALUES (?, ?, ?)",
        payload,
    )


def load_csv_to_database(csv_path: Path, db_path: Path) -> None:
    """Load the CSV into SQLite using the project -> patient -> sample hierarchy."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing input file: {csv_path}")

    df = pd.read_csv(csv_path)
    _validate_columns(df)

    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as conn:
        initialize_schema(conn)
        project_id_map = _load_projects(df, conn)
        patient_id_map = _load_patients(df, conn, project_id_map)
        _load_samples(df, conn, patient_id_map)
        _load_cell_counts(df, conn)
        conn.commit()


def main() -> None:
    load_csv_to_database(CSV_PATH, DB_PATH)
    print(f"Created database at {DB_PATH}")


if __name__ == "__main__":
    main()