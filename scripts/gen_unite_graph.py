#!/usr/bin/env python3
"""
gen_graph.py
Read benchmark CSVs, read linearity‑plot definitions from JSON
config files under a given root, generate a PNG for each
`execution_type` that compares the different kernel versions,
and produce a small HTML gallery that shows every image.

The output file names now follow the pattern:
    <app_name>-<execution_type>-<NNN>.png
where NNN is a zero‑padded counter per (app, exec_type) pair.

Example:
    python gen_graph.py ./results/ --config-root ./config/
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")          # no GUI, pure file output
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from enum import Enum

# --------------------------------------------------------------------
# 1.  Configuration objects (unchanged from the previous script)
# --------------------------------------------------------------------
class PlotType(Enum):
    NORMAL = 1
    MIN_MAX_AVG = 2
    SUCCESS_PERCENT = 3
    HISTOGRAM = 4
    LINEARITY = 5


class PlotParams:
    """Container for seaborn plotting parameters."""
    def __init__(
        self,
        x: str,
        y: str,
        hue: str,
        title: str,
        x_lbl: str = "",
        y_lbl: str = "",
        hue_lbl: str = "",
        shape: str = "lineplot",
    ):
        self.x = x
        self.y = y
        self.hue = hue
        self.title = title
        self.x_lbl = x_lbl
        self.y_lbl = y_lbl
        self.hue_lbl = hue_lbl
        self.shape = shape


# --------------------------------------------------------------------
# 2.  Utility helpers
# --------------------------------------------------------------------
def extract_metadata(filepath: str) -> Tuple[str, str]:
    """Pull out kernel_version and campaign_name from CSV header."""
    kernel_version = "Unknown"
    campaign_name = "Unknown"
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("# kernel:"):
                    content = line.replace("# kernel:", "").strip()
                    tokens = shlex.split(content)
                    if len(tokens) >= 3:
                        kernel_version = tokens[2]
                elif line.startswith("# benchmark_campaign_name:"):
                    campaign_name = line.split(":", 1)[1].strip()
                if kernel_version != "Unknown" and campaign_name != "Unknown":
                    break
    except Exception as e:
        print(f"Error reading metadata from {filepath}: {e}")
    return kernel_version, campaign_name


def discover_csv_files(paths: List[str]) -> List[str]:
    """Return a flat list of CSV files found under the supplied paths."""
    csv_files: List[str] = []
    for p in paths:
        if not os.path.exists(p):
            print(f"Warning: Path {p} does not exist. Skipping.")
            continue
        if os.path.isfile(p) and p.lower().endswith(".csv"):
            csv_files.append(p)
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.lower().endswith(".csv"):
                        csv_files.append(os.path.join(root, f))
    return csv_files


def load_and_combine_csvs(file_paths: List[str]) -> Tuple[pd.DataFrame | None, str]:
    """Read all CSV files, add metadata columns and return a single DataFrame."""
    all_dfs: List[pd.DataFrame] = []
    campaign_name = "Unknown"
    for path in file_paths:
        try:
            kernel, campaign = extract_metadata(path)
            if campaign != "Unknown":
                campaign_name = campaign
        except Exception as e:
            print(f"Error extracting metadata from {path}: {e}")
            kernel, campaign = "Unknown", "Unknown"

        try:
            df = pd.read_csv(path, sep=";", comment="#", engine="python")
            df["kernel_version"] = kernel
            df["source_file"] = os.path.basename(path)
            all_dfs.append(df)
            print(f"Loaded {path} (Kernel: {kernel})")
        except Exception as e:
            print(f"Error parsing {path}: {e}")

    if not all_dfs:
        return None, campaign_name
    return pd.concat(all_dfs, ignore_index=True), campaign_name


def sanitize_filename(text: str) -> str:
    """Make a string safe to use as a filename."""
    text = re.sub(r"\s+", "_", text)        # spaces → underscores
    text = re.sub(r"[^\w\-_.]", "", text)  # strip everything else
    return text


def plot_chart(
    params: PlotParams,
    df: pd.DataFrame,
    out_dir: str,
    out_prefix: str,
) -> str:
    """
    Create a seaborn plot according to the supplied PlotParams and
    save it to out_dir/<out_prefix>.png.  Returns the full path to the file.
    """
    plt.figure(figsize=(12, 7), dpi=150)

    # Sanity checks
    for col in (params.x, params.y, params.hue):
        if col not in df.columns:
            print(f"Error: Column '{col}' not found in data.")
            plt.close()
            return ""

    try:
        sns_fun = getattr(sns, params.shape)
    except AttributeError:
        print(f"Error: seaborn has no function '{params.shape}'.")
        plt.close()
        return ""

    ax = sns_fun(
        data=df,
        x=params.x,
        y=params.y,
        hue=params.hue,
        marker="o",
    )

    ax.set_title(params.title)
    ax.set_xlabel(params.x_lbl or params.x)
    ax.set_ylabel(params.y_lbl or params.y)
    if params.hue_lbl:
        ax.legend(title=params.hue_lbl, bbox_to_anchor=(1.05, 1), loc="upper left")
    else:
        ax.legend(title=params.hue, bbox_to_anchor=(1.05, 1), loc="upper left")

    ax.grid(True, linestyle="--", alpha=0.6)
    plt.tight_layout()

    out_path = os.path.join(out_dir, f"{out_prefix}.png")
    plt.savefig(out_path)
    plt.close()
    print(f"Saved plot to: {out_path}")
    return out_path


# --------------------------------------------------------------------
# 3.  Read the JSON config files (keep per‑app mapping)
# --------------------------------------------------------------------
def read_config_plots(config_root: str) -> Dict[str, List[dict]]:
    """
    Walk the directory tree under config_root, load every *.json file,
    and return a mapping:
        { application_name: [plot_dict, …] }
    Only *linearity* plot definitions are kept.
    """
    plots_by_app: Dict[str, List[dict]] = {}
    for root, _, files in os.walk(config_root):
        for f in files:
            if not f.lower().endswith(".json"):
                continue
            json_path = os.path.join(root, f)
            try:
                with open(json_path, "r", encoding="utf-8") as ff:
                    data = json.load(ff)
            except Exception as e:
                print(f"Failed to load {json_path}: {e}")
                continue

            apps = data.get("applications", [])
            linearity_plots = [
                p for p in data.get("plots", []) if p.get("type") == "linearity"
            ]

            for app in apps:
                name = app.get("name")
                if not name:
                    continue
                plots_by_app.setdefault(name, []).extend(linearity_plots)

    return plots_by_app


# --------------------------------------------------------------------
# 4.  Main entry point
# --------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate linearity plots from benchmark CSVs."
    )
    parser.add_argument(
        "csv_dirs", nargs="+", help="Directories that contain CSV files."
    )
    parser.add_argument(
        "--config-root",
        default="config",
        help="Root directory that contains the JSON config files (default: config/).",
    )
    parser.add_argument(
        "--output-dir",
        default="plots",
        help="Directory where PNGs and the index.html will be written.",
    )
    args = parser.parse_args()

    csv_dirs = [os.path.abspath(p) for p in args.csv_dirs]
    config_root = os.path.abspath(args.config_root)
    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    # 4.1  Discover and load CSV files
    csv_files = discover_csv_files(csv_dirs)
    if not csv_files:
        print("No CSV files found. Exiting.")
        sys.exit(1)

    combined_df, campaign_name = load_and_combine_csvs(csv_files)
    if combined_df is None:
        print("No valid data loaded. Exiting.")
        sys.exit(1)

    # 4.2  Read plot definitions from JSON (per‑app mapping)
    plots_by_app = read_config_plots(config_root)
    if not plots_by_app:
        print(f"No linearity plots found under {config_root}. Exiting.")
        sys.exit(0)

    # 4.3  Generate a separate plot for each execution_type
    generated: List[Tuple[str, str]] = []          # (title, relative_path)
    exec_types = combined_df["execution_type"].unique()
    # Counter per (app, exec_type) pair to guarantee unique file names
    counter: Dict[Tuple[str, str], int] = {}

    for app_name, plot_defs in plots_by_app.items():
        for exec_type in exec_types:
            sub_df = combined_df[combined_df["execution_type"] == exec_type]
            for plot_def in plot_defs:
                # Required columns
                x = plot_def.get("x")
                y = plot_def.get("y")
                if any(col not in sub_df.columns for col in (x, y)):
                    print(f"Skipping plot for execution_type '{exec_type}' "
                          f"(missing column).")
                    continue

                title = plot_def.get("title", f"{exec_type} – {y}")
                x_lbl = plot_def.get("x_lbl", x)
                y_lbl = plot_def.get("y_lbl", y)
                shape = plot_def.get("shape", "lineplot")

                # We always compare kernel versions → hue = kernel_version
                params = PlotParams(
                    x=x,
                    y=y,
                    hue="kernel_version",
                    title=title,
                    x_lbl=x_lbl,
                    y_lbl=y_lbl,
                    hue_lbl="Kernel",          # optional legend label
                    shape=shape,
                )

                # ---- unique file name -------------------------------------------------
                key = (app_name, exec_type)
                counter[key] = counter.get(key, 0) + 1
                suffix = f"{counter[key]:03d}"
                out_prefix = (
                    f"{sanitize_filename(app_name)}-"
                    f"{sanitize_filename(exec_type)}-{suffix}"
                )
                out_path = plot_chart(params, sub_df, out_dir, out_prefix)
                if out_path:
                    rel_path = os.path.relpath(out_path, out_dir)
                    generated.append((title, rel_path))

    if not generated:
        print("No plots were created.")
        sys.exit(0)

    # 4.4  Create a simple HTML gallery
    html_path = os.path.join(out_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n<html lang='en'>\n<head>\n")
        f.write("  <meta charset='utf-8'>\n")
        f.write("  <title>Benchmark Plot Gallery</title>\n")
        f.write("  <style>\n")
        f.write("    body { font-family: Arial, sans-serif; margin: 20px; }\n")
        f.write("    .plot { margin-bottom: 40px; }\n")
        f.write("    .plot img { max-width: 100%; height: auto; }\n")
        f.write("    h2 { margin-top: 60px; }\n")
        f.write("  </style>\n")
        f.write("</head>\n<body>\n")
        f.write("  <h1>Benchmark Plot Gallery</h1>\n")
        for title, rel_path in generated:
            f.write("  <div class='plot'>\n")
            f.write(f"    <h2>{title}</h2>\n")
            f.write(f"    <img src='{rel_path}' alt='{title}'>\n")
            f.write("  </div>\n")
        f.write("</body>\n</html>")

    print(f"\nAll plots written to: {out_dir}")
    print(f"Opening {html_path} in Firefox.")
    subprocess.run(["firefox", f"file://{html_path}"], check=False)


if __name__ == "__main__":
    main()
