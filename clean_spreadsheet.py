#!/usr/bin/env python3
"""Clean a messy CSV/Excel file.

Usage:
    python clean_spreadsheet.py messy.csv                 # writes messy_clean.csv
    python clean_spreadsheet.py messy.xlsx -o tidy.xlsx
    python clean_spreadsheet.py messy.csv --date-cols "Order Date,Ship Date"

What it does:
  * normalizes column names (snake_case, no stray spaces/symbols)
  * trims whitespace and turns "", "N/A", "null", "-" etc. into real blanks
  * drops fully empty rows and columns
  * converts date-like columns to ISO format (YYYY-MM-DD)
  * converts currency/percent-looking columns ("$1,234.50", "12%") to numbers
  * removes duplicate rows
Requires: pandas (plus openpyxl for .xlsx files).
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

NULL_TOKENS = {"", "n/a", "na", "null", "none", "nan", "-", "--", "?", "#n/a"}


def load(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, dtype=object)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, dtype=object, encoding=enc, skipinitialspace=True)
        except UnicodeDecodeError:
            continue
    sys.exit("Could not decode file as CSV.")


def snake(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()
    return name or "column"


def unique(names):
    seen, out = {}, []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def parse_dates(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except (TypeError, ValueError):  # pandas < 2.0
        return pd.to_datetime(series, errors="coerce")


def to_number(series: pd.Series):
    """Return numeric series if >=90% of non-null values look numeric, else None."""
    s = series.dropna().astype(str)
    if s.empty:
        return None
    cleaned = (
        series.astype(str)
        .str.replace(r"[\$€£,\s]", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (12.50) -> -12.50
    )
    is_pct = cleaned.str.endswith("%", na=False)
    cleaned = cleaned.str.rstrip("%")
    nums = pd.to_numeric(cleaned.where(series.notna()), errors="coerce")
    if nums.notna().sum() / len(s) < 0.9:
        return None
    nums = nums.where(~is_pct, nums / 100)
    return nums


def clean(df: pd.DataFrame, date_cols=None):
    report = {"rows_in": len(df)}

    df.columns = unique([snake(c) for c in df.columns])

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
            df[col] = df[col].map(
                lambda v: pd.NA if isinstance(v, str) and v.lower() in NULL_TOKENS else v
            )

    df = df.dropna(how="all").dropna(axis=1, how="all")

    explicit = {snake(c) for c in (date_cols or [])}
    for col in df.columns:
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        looks_dated = col in explicit or "date" in col or col.endswith("_at")
        if looks_dated:
            parsed = parse_dates(df[col])
            if parsed.notna().sum() / len(non_null) >= 0.6:
                df[col] = parsed.dt.strftime("%Y-%m-%d")
                continue
        nums = to_number(df[col])
        if nums is not None:
            df[col] = nums

    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    report["duplicates_removed"] = before - len(df)
    report["rows_out"] = len(df)
    return df, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="default: <input>_clean.<ext>")
    ap.add_argument("--date-cols", help="comma-separated columns to force as dates")
    args = ap.parse_args()

    out = args.output or args.input.with_name(f"{args.input.stem}_clean{args.input.suffix}")
    df = load(args.input)
    df, rep = clean(df, args.date_cols.split(",") if args.date_cols else None)

    if out.suffix.lower() in {".xlsx", ".xlsm"}:
        df.to_excel(out, index=False)
    else:
        df.to_csv(out, index=False)

    print(f"Rows in: {rep['rows_in']}  ->  rows out: {rep['rows_out']} "
          f"({rep['duplicates_removed']} duplicates removed)")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
