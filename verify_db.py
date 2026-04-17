from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "cell-count.csv"
DB_PATH = ROOT / "loblaw_bio_trial.db"

RECONSTRUCT_SQL = """
SELECT
    pr.project_code AS project,
    p.subject_code AS subject,
    s.condition,
    p.age,
    p.sex,
    s.treatment,
    s.response,
    s.sample_id AS sample,
    s.sample_type,
    s.time_from_treatment_start,
    MAX(CASE WHEN cc.population = 'b_cell' THEN cc.count END) AS b_cell,
    MAX(CASE WHEN cc.population = 'cd8_t_cell' THEN cc.count END) AS cd8_t_cell,
    MAX(CASE WHEN cc.population = 'cd4_t_cell' THEN cc.count END) AS cd4_t_cell,
    MAX(CASE WHEN cc.population = 'nk_cell' THEN cc.count END) AS nk_cell,
    MAX(CASE WHEN cc.population = 'monocyte' THEN cc.count END) AS monocyte
FROM samples s
JOIN patients p ON p.patient_id = s.patient_id
JOIN projects pr ON pr.project_id = p.project_id
JOIN cell_counts cc ON cc.sample_id = s.sample_id
GROUP BY
    pr.project_code,
    p.subject_code,
    s.condition,
    p.age,
    p.sex,
    s.treatment,
    s.response,
    s.sample_id,
    s.sample_type,
    s.time_from_treatment_start
ORDER BY project, subject, sample;
"""

EXPECTED_COLS = [
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
    "b_cell",
    "cd8_t_cell",
    "cd4_t_cell",
    "nk_cell",
    "monocyte",
]


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Keep only the expected columns in the expected order.
    df = df[EXPECTED_COLS]

    # Normalize common string columns without destroying missing values.
    string_cols = ["project", "subject", "condition", "sex", "treatment", "response", "sample", "sample_type"]
    for col in string_cols:
        df[col] = df[col].astype("string").str.strip()

    # Normalize missing response values so both NaN and literal "nan" compare equally.
    df["response"] = df["response"].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})

    # Numeric columns.
    numeric_cols = ["age", "time_from_treatment_start", "b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Stable sort for comparison.
    df = df.sort_values(["project", "subject", "sample"]).reset_index(drop=True)

    return df


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    base_df = normalize(pd.read_csv(CSV_PATH))

    with sqlite3.connect(DB_PATH) as conn:
        recon_df = normalize(pd.read_sql_query(RECONSTRUCT_SQL, conn))

    try:
        assert_frame_equal(base_df, recon_df, check_dtype=False, check_like=False)
        print("PASS: reconstructed database output matches the base CSV.")
    except AssertionError as e:
        print("FAIL: reconstructed database output does not match the base CSV.")
        print(str(e))

        diff = base_df.merge(recon_df, how="outer", indicator=True)
        print("\nRows only in base CSV:")
        print(diff[diff["_merge"] == "left_only"].head(10).to_string(index=False))

        print("\nRows only in reconstructed DB output:")
        print(diff[diff["_merge"] == "right_only"].head(10).to_string(index=False))


if __name__ == "__main__":
    main()