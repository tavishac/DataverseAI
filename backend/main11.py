from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import logging
from sklearn.ensemble import IsolationForest
from typing import List, Optional, Dict, Any
import math
import os

# -------------------------
# Configuration
# -------------------------
MAX_ROWS = 200000                # cap rows for analysis
MAX_FILE_BYTES = 20 * 1024**2   # 20 MB upload limit
CSV_CHUNK_SIZE = 100_000        # rows per chunk when reading CSV progressively
MIN_ROWS_FOR_ISO = 30           # min rows to run IsolationForest
MIN_NUMERIC_COLS_FOR_ISO = 2    # minimum numeric features required
ALLOWED_EXT = ('.csv', '.xlsx', '.xls')

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s - %(message)s'
)
logger = logging.getLogger("data_analyzer")

app = FastAPI(title="Advanced Data Analyzer (No-AI)", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Utility functions
# -------------------------
def sanitize(obj):
    """Recursively clean numpy/pandas types and NaN for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(i) for i in obj]
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return obj

def safe_read_csv_bytes(contents: bytes, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """
    Reads CSV in chunks to avoid memory spikes.
    Returns a DataFrame truncated to max_rows if necessary.
    """
    # Try utf-8 then fallback
    encodings = ['utf-8', 'ISO-8859-1']
    for enc in encodings:
        try:
            stream = io.BytesIO(contents)
            # If file small, simple read
            if len(contents) < 5_000_000:
                df = pd.read_csv(stream, encoding=enc)
                if df.shape[0] > max_rows:
                    logger.warning("CSV larger than MAX_ROWS — truncating for analysis.")
                    df = df.head(max_rows)
                return df
            # Otherwise stream in chunks
            reader = pd.read_csv(io.BytesIO(contents), encoding=enc, chunksize=CSV_CHUNK_SIZE)
            parts = []
            total = 0
            for chunk in reader:
                parts.append(chunk)
                total += chunk.shape[0]
                if total >= max_rows:
                    break
            df = pd.concat(parts, ignore_index=True)
            if df.shape[0] > max_rows:
                logger.warning("CSV larger than MAX_ROWS — truncating for analysis.")
                df = df.head(max_rows)
            return df
        except UnicodeDecodeError:
            logger.warning(f"Encoding {enc} failed for CSV; trying next.")
            continue
        except Exception as e:
            logger.warning(f"CSV chunk read with encoding {enc} produced error: {e}")
            continue
    raise HTTPException(status_code=400, detail="Unable to parse CSV with common encodings.")

def read_excel_bytes(contents: bytes, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """Read Excel file (single sheet)."""
    stream = io.BytesIO(contents)
    df = pd.read_excel(stream, header=0)
    if df.shape[0] > max_rows:
        logger.warning("Excel larger than MAX_ROWS — truncating for analysis.")
        df = df.head(max_rows)
    return df

def detect_duplicates(df: pd.DataFrame, sample_limit: int = 10):
    dup_mask = df.duplicated(keep=False)
    dup_count = int(dup_mask.sum())
    dup_sample = []
    if dup_count > 0:
        dup_sample = sanitize(df[dup_mask].head(sample_limit).to_dict('records'))
    return {"duplicate_count": dup_count, "duplicate_sample": dup_sample}

def basic_impute(df: pd.DataFrame, strategy: str = "median"):
    """
    Performs in-place imputation for numeric columns based on strategy.
    strategy: 'mean' | 'median' | 'mode' | 'none'
    Returns a small report of columns imputed and counts.
    """
    if strategy not in ('mean', 'median', 'mode', 'none'):
        raise ValueError("Unsupported imputation strategy.")
    report = []
    if strategy == 'none':
        return report
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            missing = int(df[col].isna().sum())
            if missing > 0:
                if strategy == 'mean':
                    val = df[col].mean()
                elif strategy == 'median':
                    val = df[col].median()
                else:
                    val = df[col].mode().iloc[0] if not df[col].mode().empty else 0
                df[col].fillna(val, inplace=True)
                report.append({"column": col, "filled": missing, "method": strategy})
        else:
            # For non-numeric, fill with mode (most frequent) for simplicity if requested
            if strategy == 'mode':
                missing = int(df[col].isna().sum())
                if missing > 0:
                    mode_val = df[col].mode().iloc[0] if not df[col].mode().empty else None
                    df[col].fillna(mode_val, inplace=True)
                    report.append({"column": col, "filled": missing, "method": "mode"})
    return report

def feature_engineer(df: pd.DataFrame):
    """
    Add simple engineered features:
    - date parsing for object cols that look like dates (if >50% parseable)
    - length for high-cardinality text
    """
    df = df.copy()
    date_like_cols = [
        col for col in df.columns
        if df[col].dtype == 'object' and 1 < df[col].nunique() < df.shape[0] * 0.95
    ]
    engineered = []
    for col in date_like_cols:
        try:
            dt = pd.to_datetime(df[col], errors='coerce')
            if dt.notna().sum() / max(1, df.shape[0]) > 0.5:
                df[f"{col}_Month"] = dt.dt.month.astype('Int64')
                df[f"{col}_DayOfWeek"] = dt.dt.dayofweek.astype('Int64')
                df[f"{col}_IsWeekend"] = (dt.dt.dayofweek >= 5).astype('Int64')
                engineered.extend([f"{col}_Month", f"{col}_DayOfWeek", f"{col}_IsWeekend"])
        except Exception as e:
            logger.debug(f"Date engineering failed for {col}: {e}")
    # Text length
    object_cols = df.select_dtypes(include=['object']).columns
    for col in object_cols:
        if df[col].nunique() > 50 and df.shape[0] > 100:
            df[f"{col}_Length"] = df[col].astype(str).map(len).astype('Int64')
            engineered.append(f"{col}_Length")
    return df, engineered

def compute_metadata(df: pd.DataFrame, engineered_cols: List[str]):
    columns_meta = []
    for col in df.columns:
        try:
            columns_meta.append({
                "name": str(col),
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique(dropna=True)),
                "is_engineered": col in engineered_cols
            })
        except Exception:
            columns_meta.append({"name": str(col), "dtype": "unknown", "missing": None, "unique": None, "is_engineered": col in engineered_cols})
    meta = {"rows": int(df.shape[0]), "cols": int(df.shape[1]), "columns": columns_meta}
    return meta

def safe_describe(df: pd.DataFrame):
    """Return describe include=all sanitized."""
    try:
        d = df.describe(include='all', datetime_is_numeric=False).to_dict()
        return sanitize(d)
    except Exception as e:
        logger.warning("describe() failed; returning basic stats.")
        stats = {}
        for col in df.columns:
            try:
                stats[col] = {
                    "dtype": str(df[col].dtype),
                    "missing": int(df[col].isna().sum()),
                    "unique": int(df[col].nunique(dropna=True))
                }
                if pd.api.types.is_numeric_dtype(df[col]):
                    stats[col].update({
                        "mean": float(df[col].dropna().mean()) if df[col].dropna().size else None,
                        "std": float(df[col].dropna().std()) if df[col].dropna().size else None,
                        "min": float(df[col].dropna().min()) if df[col].dropna().size else None,
                        "max": float(df[col].dropna().max()) if df[col].dropna().size else None,
                    })
            except Exception:
                stats[col] = {"error": "could not compute stats"}
        return sanitize(stats)

def encode_for_corr(df: pd.DataFrame, max_unique_for_factorize: int = 500):
    """
    Returns a copy of df where categorical columns are factorized (safe integer codes).
    This allows correlation computations with mixed types but keep in mind factorization
    imposes arbitrary ordering; use with caution. Only factorize columns with reasonable cardinality.
    """
    df_enc = df.copy()
    factorized_cols = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            if df[col].nunique(dropna=True) <= max_unique_for_factorize:
                df_enc[col] = pd.factorize(df[col].astype(str))[0].astype('float')
                factorized_cols.append(col)
            else:
                # drop extremely high-card columns for correlation
                df_enc.drop(columns=[col], inplace=True)
    return df_enc, factorized_cols

def correlation_pairs(df: pd.DataFrame, threshold: float = 0.7, top_n: int = 10):
    """Compute top correlated pairs (by absolute value) using numeric/factorized columns."""
    if df.select_dtypes(include=np.number).shape[1] < 2:
        return []
    corr = df.corr().fillna(0)
    pairs = []
    seen = set()
    for i in corr.columns:
        for j in corr.columns:
            if i == j or (j, i) in seen:
                continue
            val = corr.loc[i, j]
            if abs(val) >= threshold:
                pairs.append({"x": i, "y": j, "corr": float(val)})
                seen.add((i, j))
    pairs = sorted(pairs, key=lambda p: abs(p['corr']), reverse=True)[:top_n]
    return pairs

def run_isolation_forest(df: pd.DataFrame, numeric_cols: List[str], contamination='auto'):
    """
    Runs IsolationForest on numeric columns. Returns indices of outliers and per-index anomaly score.
    Also returns the trained model (if required).
    """
    result = {"outlier_indices": [], "scores": {}}
    if len(numeric_cols) < MIN_NUMERIC_COLS_FOR_ISO or df.shape[0] < MIN_ROWS_FOR_ISO:
        return result
    X = df[numeric_cols].copy()
    X = X.fillna(X.median())
    try:
        model = IsolationForest(contamination=contamination, random_state=42)
        model.fit(X)
        preds = model.predict(X)
        scores = model.decision_function(X)  # higher -> more normal; lower -> more anomalous
        outlier_mask = preds == -1
        indices = X.index[outlier_mask].tolist()
        result["outlier_indices"] = [int(i) for i in indices]
        # store negative score (more negative => stronger anomaly)
        result["scores"] = {int(idx): float(scores[idx]) for idx in range(len(scores)) if outlier_mask[idx]}
    except Exception as e:
        logger.error(f"IsolationForest failed: {e}")
    return result

def explain_outliers(df: pd.DataFrame, outlier_indices: List[int], numeric_cols: List[str], top_k_features: int = 5):
    """
    For each outlier index, compute a simple explanation:
    - For each numeric column, compute z-like score relative to median & MAD: deviation = (value - median) / (mad_or_std)
    - Rank features by absolute deviation and return top_k for that row.
    """
    explanations = {}
    if len(outlier_indices) == 0 or len(numeric_cols) == 0:
        return explanations
    medians = df[numeric_cols].median()
    mads = (df[numeric_cols].subtract(medians)).abs().median()
    # fallback to std if mad is zero
    stds = df[numeric_cols].std().replace(0, np.nan)
    for idx in outlier_indices:
        if idx not in df.index:
            continue
        row = df.loc[idx, numeric_cols]
        deviations = {}
        for col in numeric_cols:
            val = row[col]
            if pd.isna(val):
                continue
            denom = mads[col] if not pd.isna(mads[col]) and mads[col] != 0 else stds[col] if not pd.isna(stds[col]) and stds[col] != 0 else 1.0
            dev = float((val - medians[col]) / denom) if denom != 0 else 0.0
            deviations[col] = dev
        # take top features by absolute deviation
        sorted_feats = sorted(deviations.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k_features]
        explanations[int(idx)] = [{"feature": f, "deviation": float(round(d, 4)), "value": sanitize(df.loc[idx, f])} for f, d in sorted_feats]
    return explanations

def make_figures(df: pd.DataFrame, numeric_cols: List[str], categorical_cols: List[str], corr_pairs: List[Dict[str, Any]]):
    """
    Build Plotly-compatible figure dictionaries for frontend rendering.
    We do not import plotly here — we just return dicts that Plotly can consume.
    """
    figures = []

    # Correlation heatmap
    if len(numeric_cols) >= 2:
        corr_mat = df[numeric_cols].corr()
        figures.append({
            "id": "heatmap_corr",
            "type": "heatmap",
            "figure": {
                "data": [{
                    "z": corr_mat.values.tolist(),
                    "x": corr_mat.columns.tolist(),
                    "y": corr_mat.columns.tolist(),
                    "type": "heatmap",
                    "hovertemplate": "Correlation(%{x}, %{y}): %{z:.2f}<extra></extra>",
                }],
                "layout": {"title": {"text": "Correlation Heatmap"}, "height": 500, "width": 700}
            }
        })

    # Scatter plots for correlated pairs
    for pair in corr_pairs[:5]:
        x, y = pair['x'], pair['y']
        df_xy = df[[x, y]].dropna()
        figures.append({
            "id": f"scatter_{x}_vs_{y}",
            "type": "scatter",
            "figure": {
                "data": [{
                    "x": df_xy[x].tolist(),
                    "y": df_xy[y].tolist(),
                    "mode": "markers",
                    "type": "scatter",
                    "name": f"{x} vs {y}"
                }],
                "layout": {"title": {"text": f"Scatter: {x} vs {y}"}, "height": 450}
            }
        })

    # Histogram for each numeric column (limited to avoid huge payload)
    for col in numeric_cols[:10]:
        figures.append({
            "id": f"hist_{col}",
            "type": "histogram",
            "figure": {
                "data": [{"x": df[col].dropna().tolist(), "type": "histogram", "nbinsx": 30}],
                "layout": {"title": {"text": f"Distribution of {col}"}, "height": 400}
            }
        })

    # Bar charts for categorical (top 10 categories)
    for col in categorical_cols[:10]:
        counts = df[col].value_counts(dropna=True).head(10)
        if counts.shape[0] > 1:
            figures.append({
                "id": f"bar_{col}",
                "type": "bar",
                "figure": {
                    "data": [{"x": counts.index.astype(str).tolist(), "y": counts.values.tolist(), "type": "bar"}],
                    "layout": {"title": {"text": f"Top categories in {col}"}, "height": 400}
                }
            })

    # Box plot: pick first numeric and a low-cardinality categorical
    if numeric_cols:
        num = numeric_cols[0]
        cat = None
        for c in categorical_cols:
            n_unique = int(df[c].nunique(dropna=True))
            if 2 <= n_unique <= 10:
                cat = c
                break
        if cat:
            figures.append({
                "id": f"box_{num}_by_{cat}",
                "type": "box",
                "figure": {
                    "data": [{
                        "x": df[cat].astype(str).tolist(),
                        "y": df[num].tolist(),
                        "type": "box",
                        "boxpoints": "outliers"
                    }],
                    "layout": {"title": {"text": f"{num} by {cat}"}, "height": 450}
                }
            })

    return figures

# -------------------------
# Core pipeline (single function used by endpoints)
# -------------------------
def analyze_dataframe_pipeline(
    df: pd.DataFrame,
    impute_strategy: str = "none",
    corr_threshold: float = 0.7,
    corr_top_n: int = 10,
    return_figures: bool = True
):
    """
    Full analysis pipeline returning a dict with:
    meta, summary, corr_pairs, figures, outliers (with explanation), duplicates, sample_rows, column_names
    """
    # drop fully empty rows/columns
    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
    original_columns = df.columns.tolist()

    # Duplicate detection
    duplicates = detect_duplicates(df)

    # Optional: impute
    impute_report = []
    if impute_strategy != "none":
        impute_report = basic_impute(df, strategy=impute_strategy)

    # Feature engineering
    df_fe, engineered_cols = feature_engineer(df)

    # Limit rows for safety
    if df_fe.shape[0] > MAX_ROWS:
        logger.warning(f"Truncating dataset to {MAX_ROWS} rows.")
        df_fe = df_fe.head(MAX_ROWS).copy()

    # Metadata & summary
    meta = compute_metadata(df_fe, engineered_cols)
    summary = safe_describe(df_fe)

    # Correlation: factorize categorical and compute pairs
    df_for_corr, factored = encode_for_corr(df_fe)
    corr_pairs = correlation_pairs(df_for_corr, threshold=corr_threshold, top_n=corr_top_n)

    # Create figures if requested
    numeric_cols = df_fe.select_dtypes(include=np.number).columns.tolist()
    categorical_cols = df_fe.select_dtypes(include=['object', 'category', 'bool']).columns.tolist()
    figures = make_figures(df_fe, numeric_cols, categorical_cols, corr_pairs) if return_figures else []

    # Outliers detection + explanation
    iso_result = run_isolation_forest(df_fe, numeric_cols)
    outlier_indices = iso_result.get("outlier_indices", [])
    outlier_scores = iso_result.get("scores", {})
    outlier_explanations = explain_outliers(df_fe, outlier_indices, numeric_cols)

    # raw sample (first 50 original columns only)
    raw_sample = sanitize(df_fe[original_columns].head(50).to_dict('records'))

    return sanitize({
        "meta": meta,
        "summary": summary,
        "corr_pairs": corr_pairs,
        "figures": figures,
        "outliers": {
            "indices": outlier_indices,
            "scores": outlier_scores,
            "explanations": outlier_explanations
        },
        "duplicates": duplicates,
        "impute_report": impute_report,
        "raw_sample": raw_sample,
        "column_names": original_columns
    })

# -------------------------
# Request / Response models (minimal)
# -------------------------
class AnalyzeParams(BaseModel):
    impute_strategy: Optional[str] = "none"   # none | mean | median | mode
    corr_threshold: Optional[float] = 0.7
    corr_top_n: Optional[int] = 10
    return_figures: Optional[bool] = True

# -------------------------
# Endpoints
# -------------------------
@app.post("/analyze")
async def analyze(file: UploadFile = File(...), params: AnalyzeParams = None):
    """
    Full analysis endpoint. Returns metadata, summary stats, figures, outlier report, duplicates, and a raw sample.
    Query body (JSON): impute_strategy, corr_threshold, corr_top_n, return_figures
    """
    params = params or AnalyzeParams()
    filename = file.filename.lower()
    logger.info(f"Received file: {filename}")
    contents = await file.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"Uploaded file exceeds maximum allowed size of {MAX_FILE_BYTES} bytes.")

    if not any(filename.endswith(ext) for ext in ALLOWED_EXT):
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {ALLOWED_EXT}")

    # Read file content into DataFrame
    try:
        if filename.endswith(".csv"):
            df = safe_read_csv_bytes(contents)
        else:
            # excel
            df = read_excel_bytes(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File reading failed.")
        raise HTTPException(status_code=400, detail=f"Could not parse uploaded file: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Parsed dataframe is empty.")

    try:
        result = analyze_dataframe_pipeline(
            df,
            impute_strategy=params.impute_strategy,
            corr_threshold=params.corr_threshold,
            corr_top_n=params.corr_top_n,
            return_figures=params.return_figures
        )
        return result
    except Exception as e:
        logger.exception("Analysis pipeline failed.")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

@app.post("/summary")
async def summary(file: UploadFile = File(...), impute_strategy: Optional[str] = Query("none")):
    """
    Return only meta and summary stats (fast).
    """
    contents = await file.read()
    filename = file.filename.lower()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"Uploaded file exceeds maximum allowed size.")

    try:
        if filename.endswith(".csv"):
            df = safe_read_csv_bytes(contents)
        else:
            df = read_excel_bytes(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File read failed in /summary.")
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
    if impute_strategy != "none":
        try:
            basic_impute(df, impute_strategy)
        except Exception as e:
            logger.warning(f"Imputation failed in /summary: {e}")

    df_fe, engineered = feature_engineer(df)
    meta = compute_metadata(df_fe, engineered)
    summary_stats = safe_describe(df_fe)
    duplicates = detect_duplicates(df_fe)

    return sanitize({
        "meta": meta,
        "summary": summary_stats,
        "duplicates": duplicates,
        "column_names": df_fe.columns.tolist()
    })

@app.post("/visuals")
async def visuals(file: UploadFile = File(...), corr_threshold: Optional[float] = Query(0.7)):
    """
    Generate visualization metadata (plotly-compatible dicts). Designed to be light.
    """
    contents = await file.read()
    filename = file.filename.lower()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file empty.")
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"Uploaded file exceeds maximum allowed size.")

    try:
        if filename.endswith(".csv"):
            df = safe_read_csv_bytes(contents)
        else:
            df = read_excel_bytes(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File read failed in /visuals.")
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
    df_fe, engineered = feature_engineer(df)

    df_for_corr, _ = encode_for_corr(df_fe)
    pairs = correlation_pairs(df_for_corr, threshold=corr_threshold, top_n=10)
    numeric_cols = df_fe.select_dtypes(include=np.number).columns.tolist()
    categorical_cols = df_fe.select_dtypes(include=['object', 'category', 'bool']).columns.tolist()
    figures = make_figures(df_fe, numeric_cols, categorical_cols, pairs)

    return sanitize({"figures": figures, "corr_pairs": pairs})

@app.post("/outliers")
async def outliers(file: UploadFile = File(...), contamination: Optional[str] = Query("auto")):
    """
    Run only the outlier detection and return indices, scores and simple explanations.
    contamination can be 'auto' or a float in (0,0.5)
    """
    contents = await file.read()
    filename = file.filename.lower()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file empty.")
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"Uploaded file exceeds maximum allowed size.")

    try:
        if filename.endswith(".csv"):
            df = safe_read_csv_bytes(contents)
        else:
            df = read_excel_bytes(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File read failed in /outliers.")
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
    numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
    if contamination != "auto":
        try:
            contamination_val = float(contamination)
            if contamination_val <= 0 or contamination_val >= 0.5:
                raise ValueError("contamination must be between 0 and 0.5")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid contamination parameter; use 'auto' or a float between 0 and 0.5")
    else:
        contamination_val = 'auto'

    iso_result = run_isolation_forest(df, numeric_cols, contamination=contamination_val)
    outlier_indices = iso_result.get("outlier_indices", [])
    outlier_scores = iso_result.get("scores", {})
    explanations = explain_outliers(df, outlier_indices, numeric_cols)

    # return small sample of outlier rows
    outlier_rows = []
    if outlier_indices:
        outlier_rows = sanitize(df.loc[[i for i in outlier_indices if i in df.index]].head(50).to_dict('records'))

    return sanitize({
        "outlier_count": len(outlier_indices),
        "outlier_indices": outlier_indices,
        "outlier_scores": outlier_scores,
        "explanations": explanations,
        "outlier_rows_sample": outlier_rows
    })

@app.get("/")
def root():
    return {"message": "Advanced Data Analyzer (No-AI) is running. Use /analyze, /summary, /visuals, /outliers."}
