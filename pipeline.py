"""Run the analysis pipeline for the Loblaw Bio clinical trial dataset."""
from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import mannwhitneyu
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "loblaw_bio_trial.db"
OUTPUTS = ROOT / "outputs"
STATIC_DIR = ROOT / "static"
POPULATIONS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]


def fetch_cell_data(conn: sqlite3.Connection) -> pd.DataFrame:
    """Join projects -> patients -> samples -> cell_counts into one analysis frame."""
    query = """
        SELECT
            pr.project_code AS project,
            pa.subject_code AS subject,
            pa.age,
            pa.sex,
            s.sample_id AS sample,
            s.condition,
            s.treatment,
            s.response,
            s.sample_type,
            s.time_from_treatment_start,
            c.population,
            c.count
        FROM cell_counts c
        JOIN samples s ON s.sample_id = c.sample_id
        JOIN patients pa ON pa.patient_id = s.patient_id
        JOIN projects pr ON pr.project_id = pa.project_id
        ORDER BY pr.project_code, pa.subject_code, s.sample_id, c.population
    """
    return pd.read_sql_query(query, conn)


def build_relative_frequency_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute per-sample relative frequencies for each population.

    Returns:
        summary_short: only the required columns
        summary_full: required columns plus metadata
    """
    totals = (
        df.groupby("sample", as_index=False)["count"]
        .sum()
        .rename(columns={"count": "total_count"})
    )

    out = df.merge(totals, on="sample", how="left").copy()
    out["percentage"] = out["count"] / out["total_count"] * 100

    summary_full = out[
        [
            "sample",
            "total_count",
            "population",
            "count",
            "percentage",
            "project",
            "subject",
            "age",
            "sex",
            "condition",
            "treatment",
            "response",
            "sample_type",
            "time_from_treatment_start",
        ]
    ].sort_values(["sample", "population"]).reset_index(drop=True)

    summary_short = summary_full[
        ["sample", "total_count", "population", "count", "percentage"]
    ].copy()

    return summary_short, summary_full


def _response_subset(relative_df: pd.DataFrame) -> pd.DataFrame:
    """PBMC melanoma miraclib subset with valid response labels."""
    subset = relative_df.copy()

    subset["condition"] = subset["condition"].astype("string").str.lower()
    subset["treatment"] = subset["treatment"].astype("string").str.lower()
    subset["sample_type"] = subset["sample_type"].astype("string").str.upper()
    subset["response"] = subset["response"].astype("string").str.lower()
    subset["sex"] = subset["sex"].astype("string").str.lower()

    return subset[
        (subset["condition"] == "melanoma")
        & (subset["treatment"] == "miraclib")
        & (subset["sample_type"] == "PBMC")
        & (subset["response"].isin(["yes", "no"]))
    ].copy()


def run_population_stats(relative_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compare relative frequencies between responders and non-responders
    for melanoma PBMC miraclib samples.
    """
    subset = _response_subset(relative_df)

    rows = []
    for population in POPULATIONS:
        pop_df = subset[subset["population"] == population]
        yes = pop_df.loc[pop_df["response"] == "yes", "percentage"].dropna()
        no = pop_df.loc[pop_df["response"] == "no", "percentage"].dropna()

        if len(yes) == 0 or len(no) == 0:
            stat = float("nan")
            pval = float("nan")
        else:
            stat, pval = mannwhitneyu(yes, no, alternative="two-sided")

        rows.append(
            {
                "population": population,
                "responders_mean_pct": yes.mean(),
                "non_responders_mean_pct": no.mean(),
                "responders_median_pct": yes.median(),
                "non_responders_median_pct": no.median(),
                "mannwhitney_u": stat,
                "p_value": pval,
                "n_responders": int(len(yes)),
                "n_non_responders": int(len(no)),
            }
        )

    stats = pd.DataFrame(rows)
    stats["p_adjusted_bh"] = float("nan")

    valid = stats["p_value"].notna()
    if valid.any():
        stats.loc[valid, "p_adjusted_bh"] = multipletests(
            stats.loc[valid, "p_value"], method="fdr_bh"
        )[1]

    stats["significant_0_05"] = stats["p_adjusted_bh"] < 0.05
    return stats


def create_boxplots(relative_df: pd.DataFrame, out_dir: Path) -> None:
    """Plot population relative frequencies for responders vs non-responders, one per population."""
    subset = _response_subset(relative_df)

    for population in POPULATIONS:
        # Create figure with dark theme
        fig, ax = plt.subplots(figsize=(5, 3.5), facecolor='#0f172a')
        ax.set_facecolor('#1f2937')

        pop_df = subset[subset["population"] == population]
        yes = pop_df.loc[pop_df["response"] == "yes", "percentage"].to_numpy()
        no = pop_df.loc[pop_df["response"] == "no", "percentage"].to_numpy()

        # Create boxplot with custom colors for dark theme
        bp = ax.boxplot([yes, no], tick_labels=["Responder", "Non-responder"], showfliers=False,
                       patch_artist=True,
                       boxprops=dict(facecolor='#60a5fa', color='#60a5fa'),
                       capprops=dict(color='#60a5fa'),
                       whiskerprops=dict(color='#60a5fa'),
                       flierprops=dict(color='#60a5fa', markeredgecolor='#60a5fa'),
                       medianprops=dict(color='#34d399'))

        ax.set_title(f"{population.replace('_', ' ').title()} - Melanoma PBMC on Miraclib",
                    color='#e5e7eb', fontsize=11)
        ax.set_ylabel("Relative frequency (%)", color='#e5e7eb')
        ax.tick_params(axis='x', rotation=20, colors='#e5e7eb')
        ax.tick_params(axis='y', colors='#e5e7eb')

        # Set spine colors
        for spine in ax.spines.values():
            spine.set_edgecolor('#334155')

        fig.tight_layout()
        fig.savefig(out_dir / f"{population}_boxplot.png", dpi=200, bbox_inches="tight",
                   facecolor=fig.get_facecolor())
        plt.close(fig)


def run_subset_analyses(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """
    Find melanoma baseline samples at time 0 from miraclib-treated patients for all sample types.
    Returns a dict of DataFrames, one per sample type, with aggregated population counts.
    """
    sample_types = ['PBMC', 'WB']
    results = {}
    
    for sample_type in sample_types:
        query = f"""
            SELECT
                pr.project_code AS project,
                pa.subject_code AS subject,
                pa.sex,
                pa.age,
                s.sample_id AS sample,
                s.response,
                s.treatment,
                s.sample_type,
                s.time_from_treatment_start,
                SUM(CASE WHEN c.population = 'b_cell' THEN c.count ELSE 0 END) AS b_cell,
                SUM(CASE WHEN c.population = 'cd8_t_cell' THEN c.count ELSE 0 END) AS cd8_t_cell,
                SUM(CASE WHEN c.population = 'cd4_t_cell' THEN c.count ELSE 0 END) AS cd4_t_cell,
                SUM(CASE WHEN c.population = 'nk_cell' THEN c.count ELSE 0 END) AS nk_cell,
                SUM(CASE WHEN c.population = 'monocyte' THEN c.count ELSE 0 END) AS monocyte
            FROM samples s
            JOIN patients pa ON pa.patient_id = s.patient_id
            JOIN projects pr ON pr.project_id = pa.project_id
            JOIN cell_counts c ON c.sample_id = s.sample_id
            WHERE LOWER(s.condition) = 'melanoma'
              AND UPPER(s.sample_type) = '{sample_type}'
              AND LOWER(s.treatment) = 'miraclib'
              AND s.time_from_treatment_start = 0
            GROUP BY
                pr.project_code,
                pa.subject_code,
                pa.sex,
                pa.age,
                s.sample_id,
                s.response,
                s.treatment,
                s.sample_type,
                s.time_from_treatment_start
            ORDER BY pr.project_code, pa.subject_code, s.sample_id
        """
        results[sample_type] = pd.read_sql_query(query, conn)
    
    return results


def answer_question(conn: sqlite3.Connection) -> float:
    """
    Answer the question:
    Considering melanoma males, what is the average number of B cells for responders at time=0?
    """
    query = """
        SELECT AVG(c.count) AS avg_b_cell
        FROM cell_counts c
        JOIN samples s ON s.sample_id = c.sample_id
        JOIN patients pa ON pa.patient_id = s.patient_id
        JOIN projects pr ON pr.project_id = pa.project_id
        WHERE LOWER(s.condition) = 'melanoma'
          AND LOWER(pa.sex) IN ('m', 'male')
          AND LOWER(s.response) = 'yes'
          AND s.time_from_treatment_start = 0
          AND LOWER(s.sample_type) = 'pbmc'
          AND c.population = 'b_cell'
    """
    value = pd.read_sql_query(query, conn).iloc[0, 0]
    return float(value) if pd.notna(value) else float("nan")


def write_outputs(
    summary_short: pd.DataFrame,
    summary_full: pd.DataFrame,
    stats_df: pd.DataFrame,
    subset_dfs: dict[str, pd.DataFrame],
    answer: float,
) -> None:
    """Persist analysis outputs for dashboarding and grading."""
    OUTPUTS.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)

    summary_short.to_csv(OUTPUTS / "summary_table.csv", index=False)
    summary_full.to_csv(OUTPUTS / "summary_table_full.csv", index=False)
    stats_df.to_csv(OUTPUTS / "response_stats.csv", index=False)
    
    # Save subset data for each sample type
    for sample_type, df in subset_dfs.items():
        df.to_csv(OUTPUTS / f"baseline_subset_{sample_type.lower()}.csv", index=False)

    plot_path = OUTPUTS / "response_boxplot.png"
    create_boxplots(summary_full, STATIC_DIR)
    # For backward compatibility, copy the first one or something, but since we're changing, remove the old
    # shutil.copyfile(plot_path, STATIC_DIR / "response_boxplot.png")

    # Generate report for all sample types
    report_lines = [
        "Question answer summary:",
        f"Average B cells for melanoma male responders at time=0 (PBMC): {answer:.2f}",
        "",
    ]
    
    for sample_type, df in subset_dfs.items():
        subset_projects = df.groupby("project")["sample"].nunique().to_dict()
        subset_responses = df.groupby("response")["subject"].nunique().to_dict()
        subset_sex = df.groupby("sex")["subject"].nunique().to_dict()
        
        report_lines.extend([
            f"Baseline melanoma {sample_type} miraclib subset at time=0:",
            f"Samples by project: {subset_projects}",
            f"Distinct subjects by response: {subset_responses}",
            f"Distinct subjects by sex: {subset_sex}",
            "",
        ])
    
    report_lines.extend([
        "AI model note:",
        "This analysis can be augmented with AI models such as quintazide to support predictive feature selection and response modeling.",
        "",
        "Statistics note:",
        "Significance is assessed with Mann-Whitney U and Benjamini-Hochberg FDR correction.",
    ])
    (OUTPUTS / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")


def main() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        df = fetch_cell_data(conn)
        summary_short, summary_full = build_relative_frequency_table(df)
        stats_df = run_population_stats(summary_full)
        subset_dfs = run_subset_analyses(conn)
        answer = answer_question(conn)

    write_outputs(summary_short, summary_full, stats_df, subset_dfs, answer)
    print("Pipeline complete. Outputs written to outputs/")


if __name__ == "__main__":
    main()