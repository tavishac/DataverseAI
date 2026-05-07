'''
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import numpy as np
from sklearn.ensemble import IsolationForest
import os
import json
import logging

# Set up logging for better error visibility
logging.basicConfig(level=logging.INFO)

# Optional: OpenAI client for NLG summary
client = None
if os.environ.get("OPENAI_API_KEY"):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        logging.info("OpenAI client initialized for NLG summaries.")
    except ImportError:
        logging.warning("Warning: 'openai' library not installed. AI summary will be unavailable.")
    except Exception as e:
        logging.warning(f"Error initializing OpenAI client: {e}. AI summary will be unavailable.")
else:
    logging.info("OPENAI_API_KEY not found. AI summary will be unavailable.")


app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ROWS = 200000

# ✅ Common Plotly config (used for all charts)
PLOTLY_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "plot_download",
        "height": 600,
        "width": 800,
        "scale": 2
    }
}


def sanitize(obj):
    """Recursively cleans numpy types and NaN values from dictionaries/lists for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(elem) for elem in obj]
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif pd.isna(obj):
        return None
    else:
        return obj


def feature_engineer(df: pd.DataFrame):
    """
    Performs basic feature engineering for date-like and long-text columns.
    This helps in providing more features for the anomaly detection model.
    """
    # 1. Date Feature Engineering
    date_like_cols = [
        col for col in df.columns 
        if df[col].dtype == 'object' and df[col].nunique() > 1 and df[col].nunique() < df.shape[0] * 0.9
    ]

    for col in date_like_cols:
        try:
            # Attempt to parse to datetime
            dt_series = pd.to_datetime(df[col], errors='coerce')
            # Only proceed if more than 50% of values are valid dates
            if dt_series.notna().sum() / df.shape[0] > 0.5:
                df[f'{col}_Month'] = dt_series.dt.month.astype('category')
                df[f'{col}_DayOfWeek'] = dt_series.dt.day_name().astype('category')
                df[f'{col}_IsWeekend'] = dt_series.dt.weekday >= 5
        except Exception as e:
            logging.debug(f"Date feature engineering failed for {col}: {e}")
            pass

    # 2. Text Feature Engineering (Length)
    object_cols = df.select_dtypes(include=['object']).columns
    for col in object_cols:
        # Check if the column is high cardinality and has potentially meaningful text content
        if df[col].nunique() > 50 and df.shape[0] > 100:
            df[f'{col}_Length'] = df[col].astype(str).apply(len)

    return df


def detect_outliers(df: pd.DataFrame):
    """Detects outliers using Isolation Forest on all numeric features."""
    # Select only numeric columns that have at least some variance
    numeric_cols = df.select_dtypes(include=np.number).columns
    valid_numeric_cols = [
        col for col in numeric_cols 
        if df[col].nunique() > 1 and df[col].count() > 0
    ]
    
    outliers = []

    if len(valid_numeric_cols) >= 2 and df.shape[0] > 50:
        # Impute NaNs with median for anomaly detection consistency
        X = df[valid_numeric_cols].fillna(df[valid_numeric_cols].median())
        
        try:
            model = IsolationForest(contamination='auto', random_state=42, n_jobs=-1)
            model.fit(X)
            is_outlier = model.predict(X)
            outlier_indices = X[is_outlier == -1].index.tolist()
            if outlier_indices:
                outliers = [int(i) for i in outlier_indices]
        except Exception as e:
            logging.error(f"Isolation Forest failed: {e}")

    return outliers


def generate_nlg_summary(meta, summary, corr_pairs, outliers):
    """Generates a cognitive summary using the OpenAI API (or Gemini API if configured)."""
    if not client:
        return "NLG Summary service is unavailable. Ensure the 'openai' library is installed and OPENAI_API_KEY is set."

    # Subsetting the descriptive statistics for a cleaner prompt
    key_stats = {}
    for col, stats in summary.items():
        if isinstance(stats, dict) and 'mean' in stats:
            key_stats[col] = {
                'mean': stats.get('mean', 'N/A'),
                'std': stats.get('std', 'N/A'),
                'min': stats.get('min', 'N/A'),
                'max': stats.get('max', 'N/A'),
                'unique': stats.get('unique', 'N/A'),
                'dtype': next((c['dtype'] for c in meta['columns'] if c['name'] == col), 'unknown')
            }

    stats_json = json.dumps(key_stats, indent=2, default=str)[:3000]

    corr_report = "\n".join([
        f"- {p['x']} vs {p['y']}: {p['corr']:.3f}" for p in corr_pairs
    ])

    prompt = f"""
    You are a helpful, senior data scientist. Analyze the provided dataset metadata, key statistics, and anomaly report.
    The goal is to provide a quick, professional assessment for a data team.

    1. Provide a **Cognitive Summary** (about 3 sentences) of the dataset's overall shape, focusing on key features (e.g., scale, balance, notable high/low variance columns).
    2. Provide 2-3 **Actionable Recommendations** (e.g., handling missing data in a specific column, cleaning outliers, or potential modeling ideas based on correlations).
    3. Format the response clearly using markdown. Use bold markdown (**text**) for key points.

    ---
    ### Dataset Metadata
    Rows: {meta['rows']:,}
    Columns: {meta['cols']}
    Engineered Features Added: {sum(1 for c in meta['columns'] if c['is_engineered'])}

    ### Top Correlations (Absolute Value)
    {corr_report if corr_report else 'No strong correlations (|\rho| > 0.7) found.'}

    ### Anomaly Report
    Outliers Detected (IsolationForest): {len(outliers)} rows

    ### Key Column Statistics Sample
    {stats_json}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a concise, analytical data science assistant who provides professional summaries and recommendations."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"NLG Summary generation failed: {e}")
        return f"NLG Summary unavailable due to API error: {e}"


def analyze_dataframe(df: pd.DataFrame):
    """Main data analysis workflow."""
    # Drop rows/columns that are entirely NaN
    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
    
    # Store initial column names before engineering
    original_column_names = df.columns.tolist()

    df = feature_engineer(df)

    # Limit to MAX_ROWS if the dataset is too large, but run analysis on the head
    if df.shape[0] > MAX_ROWS:
        logging.warning(f"Dataset truncated to {MAX_ROWS} rows for analysis.")
        df = df.head(MAX_ROWS).copy()

    # --- Metadata Calculation ---
    meta = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": [
            {
                "name": str(col),
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique(dropna=True)),
                "is_engineered": any(x in str(col) for x in ['Month', 'DayOfWeek', 'Length', 'IsWeekend'])
            }
            for col in df.columns
        ]
    }

    # --- Summary Statistics ---
    summary = sanitize(df.describe(include="all").to_dict())
    
    # --- Correlation & Plot Generation ---
    corr_pairs = []
    figures = []
    numeric_cols = df.select_dtypes(include=np.number)
    numeric_cols_names = numeric_cols.columns.tolist()
    categorical_cols_names = df.select_dtypes(include=['object', 'category']).columns.tolist()

    # 1. Correlation Heatmap
    if len(numeric_cols.columns) >= 2:
        corr_matrix = numeric_cols.corr()
        heatmap_fig = {
            "id": "heatmap_corr",
            "figure": {
                "data": [{
                    "z": corr_matrix.values.tolist(),
                    "x": corr_matrix.columns.tolist(),
                    "y": corr_matrix.columns.tolist(),
                    "type": "heatmap",
                    "colorscale": "Plasma", # Changed to Plasma for visibility
                    "hovertemplate": "Correlation(%{x}, %{y}): %{z:.2f}<extra></extra>",
                }],
                "layout": {"title": {"text": "Correlation Heatmap"}, "height": 550, "width": 650},
                "config": PLOTLY_CONFIG
            }
        }
        figures.append(heatmap_fig)

        # Top correlations extraction
        corr_abs_matrix = corr_matrix.abs()
        already_seen = set()
        for i in corr_abs_matrix.columns:
            for j in corr_abs_matrix.columns:
                if i != j and (j, i) not in already_seen and abs(corr_matrix.loc[i, j]) >= 0.7:
                    actual_corr = corr_matrix.loc[i, j]
                    corr_pairs.append({"x": i, "y": j, "corr": float(actual_corr)})
                    already_seen.add((i, j))
        # Sort by absolute correlation and take top 10
        corr_pairs = sorted(corr_pairs, key=lambda x: abs(x["corr"]), reverse=True)[:10]

        # 2. Scatter plots for top correlated pairs
        for pair in corr_pairs[:5]:
            col_x, col_y = pair['x'], pair['y']
            plot_df = df[[col_x, col_y]].dropna()
            fig = {
                "id": f"scatter_{col_x}_vs_{col_y}",
                "figure": {
                    "data": [{
                        "x": plot_df[col_x].tolist(),
                        "y": plot_df[col_y].tolist(),
                        "mode": "markers",
                        "type": "scatter",
                        "marker": {"color": "#1f77b4", "size": 6}, # Default Plotly blue
                        "name": f"{col_x} vs {col_y}",
                        "hovertemplate": f"{col_x}: %{{x}}<br>{col_y}: %{{y}}<extra></extra>"
                    }],
                    "layout": {"title": {"text": f"Scatter Plot: {col_x} vs {col_y}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)

    # 3. Box plot (Numeric vs Low-Cardinality Category)
    if numeric_cols_names and categorical_cols_names:
        num_col = numeric_cols_names[0]
        # Find a suitable categorical column (2 to 10 unique values)
        cat_col = next((col for col in categorical_cols_names if 2 <= df[col].nunique() <= 10), None)
        if cat_col:
            fig = {
                "id": f"boxplot_{num_col}_by_{cat_col}",
                "figure": {
                    "data": [{
                        "y": df[num_col].tolist(),
                        "x": df[cat_col].astype(str).tolist(),
                        "type": "box",
                        "boxpoints": 'outliers',
                        "marker": {"color": "darkgreen"},
                        "name": f"{num_col} by {cat_col}"
                    }],
                    "layout": {"title": {"text": f"Box Plot: {num_col} by {cat_col}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)

    # 4. Histograms (Numeric Distributions)
    for col in numeric_cols_names:
        fig = {
            "id": f"hist_{col}",
            "figure": {
                "data": [{
                    "x": numeric_cols[col].dropna().tolist(),
                    "type": "histogram",
                    "marker": {"color": "lightblue"},
                    "nbinsx": 50 # Increase bin count for better detail
                }],
                "layout": {"title": {"text": f"Distribution of {col}"}, "height": 400},
                "config": PLOTLY_CONFIG
            }
        }
        figures.append(fig)

    # 5. Bar charts (Categorical Counts)
    categorical_cols = df.select_dtypes(include=['object', 'category', 'bool'])
    for col in categorical_cols.columns:
        top_counts = df[col].value_counts(dropna=True).head(10)
        if not top_counts.empty and top_counts.shape[0] > 1:
            fig = {
                "id": f"bar_{col}",
                "figure": {
                    "data": [{
                        "x": top_counts.index.astype(str).tolist(),
                        "y": top_counts.values.tolist(),
                        "type": "bar",
                        "marker": {"color": "teal"}
                    }],
                    "layout": {"title": {"text": f"Top 10 Counts of {col}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)
            
    # --- Anomaly Detection and NLG ---
    outliers = detect_outliers(df)
    nlg_summary = generate_nlg_summary(meta, summary, corr_pairs, outliers)
    raw_data_sample = sanitize(df[original_column_names].head(50).to_dict('records'))


    return {
        "meta": meta,
        "summary": summary,
        "corr_pairs": corr_pairs,
        "figures": figures,
        "outliers": outliers,
        "nlg_summary": nlg_summary,
        "raw_data_sample": raw_data_sample,
        "column_names": original_column_names # Return original names for display
    }


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """API endpoint to upload and analyze a data file."""
    filename = file.filename.lower()
    contents = await file.read()
    df = pd.DataFrame()
    
    try:
        if filename.endswith(".csv"):
            # Attempt to read CSV with common encodings for robustness
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding='utf-8')
            except UnicodeDecodeError:
                logging.warning("UTF-8 failed, trying ISO-8859-1.")
                df = pd.read_csv(io.BytesIO(contents), encoding='ISO-8859-1')
            except Exception as e:
                logging.error(f"CSV read failed: {e}")
                raise HTTPException(status_code=400, detail=f"Could not read CSV file: {e}")

        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents), header=0)
            
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Please upload .csv, .xlsx, or .xls.")
            
        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded file is empty or could not be parsed.")
            
    except HTTPException:
        raise # Re-raise known HTTP exceptions
    except Exception as e:
        logging.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during file processing: {e}")
        
    return analyze_dataframe(df)


@app.get("/")
def root():
    return {"message": "Advanced Data Analyzer backend is running! Use /analyze to upload a file."}
'''

'''
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import numpy as np
from sklearn.ensemble import IsolationForest
import logging

# --------------------------------------------------------------------
# ✅ LOGGING CONFIGURATION
# --------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# --------------------------------------------------------------------
# ✅ FASTAPI APP INITIALIZATION
# --------------------------------------------------------------------
app = FastAPI(title="Data Analyzer Backend", version="2.0")

# Enable CORS (for frontend communication)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------
# ✅ CONSTANTS
# --------------------------------------------------------------------
MAX_ROWS = 200000

PLOTLY_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
}

# --------------------------------------------------------------------
# ✅ HELPER FUNCTIONS
# --------------------------------------------------------------------
def sanitize(obj):
    """Cleans numpy and NaN values for safe JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(x) for x in obj]
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif pd.isna(obj):
        return None
    else:
        return obj


def feature_engineer(df: pd.DataFrame):
    """Adds engineered features for datetime and text columns."""
    # Convert object columns that look like dates
    for col in df.select_dtypes(include="object").columns:
        try:
            dt = pd.to_datetime(df[col], errors="coerce")
            if dt.notna().sum() / len(dt) > 0.5:
                df[f"{col}_Month"] = dt.dt.month
                df[f"{col}_DayOfWeek"] = dt.dt.dayofweek
                df[f"{col}_IsWeekend"] = dt.dt.weekday >= 5
        except Exception:
            continue

    # Text length features
    for col in df.select_dtypes(include="object").columns:
        if df[col].nunique() > 50:
            df[f"{col}_Length"] = df[col].astype(str).apply(len)
    return df


def detect_outliers(df: pd.DataFrame):
    """Detects outliers using Isolation Forest on numeric data."""
    numeric_cols = df.select_dtypes(include=np.number).columns
    valid_cols = [c for c in numeric_cols if df[c].nunique() > 1]

    if len(valid_cols) < 2:
        return []

    X = df[valid_cols].fillna(df[valid_cols].median())
    try:
        model = IsolationForest(contamination="auto", random_state=42)
        preds = model.fit_predict(X)
        return list(df.index[preds == -1])
    except Exception as e:
        logging.warning(f"Outlier detection failed: {e}")
        return []


# --------------------------------------------------------------------
# ✅ MAIN ANALYSIS FUNCTION
# --------------------------------------------------------------------
def analyze_dataframe(df: pd.DataFrame):
    """Performs automatic dataset profiling and visualization setup."""
    df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
    if df.empty:
        raise HTTPException(status_code=400, detail="The uploaded dataset is empty.")

    df = feature_engineer(df)
    if df.shape[0] > MAX_ROWS:
        df = df.head(MAX_ROWS)

    # Metadata
    meta = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": [
            {
                "name": str(col),
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique(dropna=True)),
            }
            for col in df.columns
        ],
    }

    # Summary
    summary = sanitize(df.describe(include="all").to_dict())

    # Correlation analysis
    corr_pairs = []
    numeric = df.select_dtypes(include=np.number)
    if numeric.shape[1] >= 2:
        corr = numeric.corr()
        for i in corr.columns:
            for j in corr.columns:
                if i != j and abs(corr.loc[i, j]) >= 0.7:
                    corr_pairs.append({"x": i, "y": j, "corr": float(corr.loc[i, j])})

    # Visualization templates
    figures = []
    # Histogram
    for col in numeric.columns:
        figures.append({
            "id": f"hist_{col}",
            "figure": {
                "data": [{"x": numeric[col].dropna().tolist(), "type": "histogram"}],
                "layout": {"title": {"text": f"Histogram of {col}"}},
                "config": PLOTLY_CONFIG
            }
        })

    # Categorical bar chart
    for col in df.select_dtypes(include=["object", "category", "bool"]).columns:
        vc = df[col].value_counts().head(10)
        if len(vc) > 1:
            figures.append({
                "id": f"bar_{col}",
                "figure": {
                    "data": [{"x": vc.index.tolist(), "y": vc.values.tolist(), "type": "bar"}],
                    "layout": {"title": {"text": f"Top Categories in {col}"}},
                    "config": PLOTLY_CONFIG
                }
            })

    # Detect outliers
    outliers = detect_outliers(df)

    # Sample data
    sample = sanitize(df.head(30).to_dict("records"))

    return {
        "meta": meta,
        "summary": summary,
        "correlations": corr_pairs,
        "figures": figures,
        "outliers": outliers,
        "sample": sample,
    }

# --------------------------------------------------------------------
# ✅ API ROUTES
# --------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Data Analyzer backend is running successfully!"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """Accepts a CSV/XLSX file and returns analysis results."""
    contents = await file.read()
    try:
        if file.filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents), encoding_errors="ignore")
        elif file.filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv or .xlsx")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")

    return analyze_dataframe(df)
'''
'''
# backend.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import numpy as np
from sklearn.ensemble import IsolationForest
import os
import json
import logging
import datetime

# Set up logging for better error visibility
logging.basicConfig(level=logging.INFO)


app = FastAPI()

# Enable CORS (for development; tighten origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ROWS = 200000

# ✅ Common Plotly config (used for all charts)
PLOTLY_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "plot_download",
        "height": 600,
        "width": 800,
        "scale": 2
    }
}


def sanitize(obj):
    """Recursively clean objects to be JSON serializable:
       - handle numpy scalars, NaN/inf, pandas NaT/Timestamps, datetime, lists/dicts
    """
    # dict
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    # list / tuple
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    # numpy scalar ints/floats/bools
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    # numpy arrays -> lists
    if isinstance(obj, np.ndarray):
        return [sanitize(x) for x in obj.tolist()]
    # pandas Timestamp / datetime / numpy datetime64 -> ISO str
    if isinstance(obj, (pd.Timestamp, datetime.datetime)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    # np.datetime64
    if isinstance(obj, np.datetime64):
        try:
            # convert to python datetime
            ts = pd.to_datetime(obj).to_pydatetime()
            return ts.isoformat()
        except Exception:
            return str(obj)
    # pandas NA / NaN
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    # fallback
    return obj


def feature_engineer(df: pd.DataFrame):
    """
    Performs basic feature engineering for date-like and long-text columns.
    This helps in providing more features for the anomaly detection model.
    """
    # 1. Date Feature Engineering
    date_like_cols = [
        col for col in df.columns
        if df[col].dtype == 'object' and df[col].nunique() > 1 and df[col].nunique() < df.shape[0] * 0.9
    ]

    for col in date_like_cols:
        try:
            dt_series = pd.to_datetime(df[col], errors='coerce')
            # Only proceed if more than 50% of values are valid dates
            if dt_series.notna().sum() / max(1, df.shape[0]) > 0.5:
                df[f'{col}_Month'] = dt_series.dt.month.astype('category')
                df[f'{col}_DayOfWeek'] = dt_series.dt.day_name().astype('category')
                df[f'{col}_IsWeekend'] = (dt_series.dt.weekday >= 5).astype('bool')
        except Exception as e:
            logging.debug(f"Date feature engineering failed for {col}: {e}")
            pass

    # 2. Text Feature Engineering (Length)
    object_cols = df.select_dtypes(include=['object']).columns
    for col in object_cols:
        if df[col].nunique(dropna=True) > 50 and df.shape[0] > 100:
            df[f'{col}_Length'] = df[col].astype(str).fillna("").apply(len)

    return df


def detect_outliers(df: pd.DataFrame):
    """Detects outliers using Isolation Forest on all numeric features."""
    numeric_cols = df.select_dtypes(include=np.number).columns
    valid_numeric_cols = [
        col for col in numeric_cols
        if df[col].nunique(dropna=True) > 1 and df[col].count() > 0
    ]

    outliers = []

    if len(valid_numeric_cols) >= 2 and df.shape[0] > 50:
        X = df[valid_numeric_cols].fillna(df[valid_numeric_cols].median())
        try:
            model = IsolationForest(contamination='auto', random_state=42, n_jobs=-1)
            model.fit(X)
            is_outlier = model.predict(X)
            outlier_indices = X.index[is_outlier == -1].tolist()
            if outlier_indices:
                outliers = [int(i) for i in outlier_indices]
        except Exception as e:
            logging.error(f"Isolation Forest failed: {e}")

    return outliers


def generate_nlg_summary(meta, summary, corr_pairs, outliers):
    """Generates a cognitive summary using the OpenAI client if available."""
    if not client:
        return "NLG Summary service is unavailable. Ensure the 'openai' library is installed and OPENAI_API_KEY is set."

    # Subset key stats for a compact prompt
    key_stats = {}
    for col, stats in summary.items():
        if isinstance(stats, dict) and 'mean' in stats:
            key_stats[col] = {
                'mean': stats.get('mean', 'N/A'),
                'std': stats.get('std', 'N/A'),
                'min': stats.get('min', 'N/A'),
                'max': stats.get('max', 'N/A'),
                'unique': stats.get('unique', 'N/A'),
                'dtype': next((c['dtype'] for c in meta['columns'] if c['name'] == col), 'unknown')
            }

    stats_json = json.dumps(key_stats, indent=2, default=str)[:3000]

    corr_report = "\n".join([
        f"- {p['x']} vs {p['y']}: {p['corr']:.3f}" for p in corr_pairs
    ])

    prompt = f"""
You are a helpful, senior data scientist. Analyze the provided dataset metadata, key statistics, and anomaly report.
The goal is to provide a quick, professional assessment for a data team.

1. Provide a **Cognitive Summary** (about 3 sentences) of the dataset's overall shape, focusing on key features (e.g., scale, balance, notable high/low variance columns).
2. Provide 2-3 **Actionable Recommendations** (e.g., handling missing data in a specific column, cleaning outliers, or potential modeling ideas based on correlations).
3. Format the response clearly using markdown. Use bold markdown (**text**) for key points.

---
### Dataset Metadata
Rows: {meta['rows']:,}
Columns: {meta['cols']}
Engineered Features Added: {sum(1 for c in meta['columns'] if c.get('is_engineered'))}

### Top Correlations (Absolute Value)
{corr_report if corr_report else 'No strong correlations (|ρ| > 0.7) found.'}

### Anomaly Report
Outliers Detected (IsolationForest): {len(outliers)} rows

### Key Column Statistics Sample
{stats_json}
"""

    try:
        # Using the OpenAI client (adjust if you use a different client interface)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a concise, analytical data science assistant who provides professional summaries and recommendations."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"NLG Summary generation failed: {e}")
        return f"NLG Summary unavailable due to API error: {e}"


def analyze_dataframe(df: pd.DataFrame):
    """Main data analysis workflow."""
    # Drop rows/columns that are entirely NaN
    df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)

    # Store initial column names before engineering
    original_column_names = df.columns.tolist()

    df = feature_engineer(df)

    # Limit rows early if huge dataset
    if df.shape[0] > MAX_ROWS:
        logging.warning(f"Dataset truncated to {MAX_ROWS} rows for analysis.")
        df = df.head(MAX_ROWS).copy()

    # --- Metadata Calculation ---
    meta = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": [
            {
                "name": str(col),
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique(dropna=True)),
                "is_engineered": any(x in str(col) for x in ['Month', 'DayOfWeek', 'Length', 'IsWeekend'])
            }
            for col in df.columns
        ]
    }

    # --- Summary Statistics ---
    summary = sanitize(df.describe(include="all").to_dict())

    # --- Correlation & Plot Generation ---
    corr_pairs = []
    figures = []
    numeric_cols = df.select_dtypes(include=np.number)
    numeric_cols_names = numeric_cols.columns.tolist()
    categorical_cols_names = df.select_dtypes(include=['object', 'category']).columns.tolist()

    # 1. Correlation Heatmap
    if len(numeric_cols.columns) >= 2:
        corr_matrix = numeric_cols.corr()
        heatmap_fig = {
            "id": "heatmap_corr",
            "figure": {
                "data": [{
                    "z": corr_matrix.values.tolist(),
                    "x": corr_matrix.columns.tolist(),
                    "y": corr_matrix.columns.tolist(),
                    "type": "heatmap",
                    "colorscale": "Plasma",
                    "hovertemplate": "Correlation(%{x}, %{y}): %{z:.2f}<extra></extra>",
                }],
                "layout": {"title": {"text": "Correlation Heatmap"}, "height": 550, "width": 650},
                "config": PLOTLY_CONFIG
            }
        }
        figures.append(heatmap_fig)

        # Top correlations extraction
        corr_abs_matrix = corr_matrix.abs()
        already_seen = set()
        for i in corr_abs_matrix.columns:
            for j in corr_abs_matrix.columns:
                if i != j and (j, i) not in already_seen and abs(corr_matrix.loc[i, j]) >= 0.7:
                    actual_corr = corr_matrix.loc[i, j]
                    corr_pairs.append({"x": i, "y": j, "corr": float(actual_corr)})
                    already_seen.add((i, j))
        corr_pairs = sorted(corr_pairs, key=lambda x: abs(x["corr"]), reverse=True)[:10]

        # Scatter plots for top correlated pairs
        for pair in corr_pairs[:5]:
            col_x, col_y = pair['x'], pair['y']
            plot_df = df[[col_x, col_y]].dropna()
            fig = {
                "id": f"scatter_{col_x}_vs_{col_y}",
                "figure": {
                    "data": [{
                        "x": plot_df[col_x].tolist(),
                        "y": plot_df[col_y].tolist(),
                        "mode": "markers",
                        "type": "scatter",
                        "marker": {"color": "#1f77b4", "size": 6},
                        "name": f"{col_x} vs {col_y}",
                        "hovertemplate": f"{col_x}: %{{x}}<br>{col_y}: %{{y}}<extra></extra>"
                    }],
                    "layout": {"title": {"text": f"Scatter Plot: {col_x} vs {col_y}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)

    # 3. Box plot (Numeric vs Low-Cardinality Category)
    if numeric_cols_names and categorical_cols_names:
        num_col = numeric_cols_names[0]
        cat_col = next((col for col in categorical_cols_names if 2 <= df[col].nunique(dropna=True) <= 10), None)
        if cat_col:
            fig = {
                "id": f"boxplot_{num_col}_by_{cat_col}",
                "figure": {
                    "data": [{
                        "y": df[num_col].tolist(),
                        "x": df[cat_col].astype(str).tolist(),
                        "type": "box",
                        "boxpoints": 'outliers',
                        "marker": {"color": "darkgreen"},
                        "name": f"{num_col} by {cat_col}"
                    }],
                    "layout": {"title": {"text": f"Box Plot: {num_col} by {cat_col}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)

    # 4. Histograms (Numeric Distributions)
    for col in numeric_cols_names:
        fig = {
            "id": f"hist_{col}",
            "figure": {
                "data": [{
                    "x": numeric_cols[col].dropna().tolist(),
                    "type": "histogram",
                    "marker": {"color": "lightblue"},
                    "nbinsx": 50
                }],
                "layout": {"title": {"text": f"Distribution of {col}"}, "height": 400},
                "config": PLOTLY_CONFIG
            }
        }
        figures.append(fig)

    # 5. Bar charts (Categorical Counts)
    categorical_cols = df.select_dtypes(include=['object', 'category', 'bool'])
    for col in categorical_cols.columns:
        top_counts = df[col].value_counts(dropna=True).head(10)
        if not top_counts.empty and top_counts.shape[0] > 1:
            fig = {
                "id": f"bar_{col}",
                "figure": {
                    "data": [{
                        "x": top_counts.index.astype(str).tolist(),
                        "y": top_counts.values.tolist(),
                        "type": "bar",
                        "marker": {"color": "teal"}
                    }],
                    "layout": {"title": {"text": f"Top 10 Counts of {col}"}, "height": 450},
                    "config": PLOTLY_CONFIG
                }
            }
            figures.append(fig)

    # --- Anomaly Detection and NLG ---
    outliers = detect_outliers(df)
    nlg_summary = generate_nlg_summary(meta, summary, corr_pairs, outliers)
    # Return original column order for raw sample
    raw_data_sample = sanitize(df[original_column_names].head(50).to_dict('records'))

    result = {
        "meta": meta,
        "summary": summary,
        "corr_pairs": corr_pairs,
        "figures": figures,
        "outliers": outliers,
        "nlg_summary": nlg_summary,
        "raw_data_sample": raw_data_sample,
        "column_names": original_column_names
    }

    # Sanitize the full result (handles numpy/pandas types inside figures etc.)
    return sanitize(result)


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """API endpoint to upload and analyze a data file."""
    filename = file.filename.lower()
    contents = await file.read()
    df = pd.DataFrame()

    try:
        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding='utf-8')
            except UnicodeDecodeError:
                logging.warning("UTF-8 failed, trying ISO-8859-1.")
                df = pd.read_csv(io.BytesIO(contents), encoding='ISO-8859-1')
            except Exception as e:
                logging.error(f"CSV read failed: {e}")
                raise HTTPException(status_code=400, detail=f"Could not read CSV file: {e}")

        elif filename.endswith((".xlsx", ".xls")):
            try:
                df = pd.read_excel(io.BytesIO(contents), header=0)
            except Exception as e:
                logging.error(f"Excel read failed: {e}")
                raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")

        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Please upload .csv, .xlsx, or .xls.")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded file is empty or could not be parsed.")

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during file processing: {e}")

    try:
        result = analyze_dataframe(df)
        return result
    except Exception as e:
        logging.error(f"Analysis pipeline failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


@app.get("/")
def root():
    return {"message": "Advanced Data Analyzer backend is running! Use /analyze to upload a file."}
'''
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import numpy as np
from sklearn.ensemble import IsolationForest
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ROWS = 200000


# ---------- SANITIZE ----------
def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    return obj


# ---------- OUTLIERS ----------
def detect_outliers(df):
    num = df.select_dtypes(include=np.number)

    if num.shape[1] < 2 or df.shape[0] < 50:
        return []

    X = num.fillna(num.median())

    try:
        model = IsolationForest(random_state=42)
        preds = model.fit_predict(X)
        return [int(i) for i in np.where(preds == -1)[0]]
    except Exception as e:
        logging.error(e)
        return []


# ---------- MAIN ANALYSIS ----------
def analyze_dataframe(df):

    df = df.dropna(how='all').dropna(how='all', axis=1)

    if df.empty:
        raise ValueError("Empty dataset")

    if df.shape[0] > MAX_ROWS:
        df = df.head(MAX_ROWS)

    # META
    meta = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": [
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique())
            }
            for col in df.columns
        ]
    }

    # SUMMARY
    summary = sanitize(df.describe(include='all').to_dict())

    # CORRELATION
    corr_pairs = []
    figures = []

    num = df.select_dtypes(include=np.number)

    if num.shape[1] >= 2:
        corr = num.corr()
        cols = corr.columns

        # Heatmap
        figures.append({
            "id": "heatmap_corr",
            "figure": {
                "data": [{
                    "z": corr.values.tolist(),
                    "x": cols.tolist(),
                    "y": cols.tolist(),
                    "type": "heatmap",
                    "colorscale": "Viridis"
                }],
                "layout": {"title": "Correlation Heatmap"}
            }
        })

        # Top correlations
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                val = corr.iloc[i, j]
                if abs(val) > 0.7:
                    corr_pairs.append({
                        "x": cols[i],
                        "y": cols[j],
                        "corr": float(val)
                    })

    # HISTOGRAMS
    for col in num.columns:
        figures.append({
            "id": f"hist_{col}",
            "figure": {
                "data": [{
                    "x": df[col].dropna().tolist(),
                    "type": "histogram"
                }],
                "layout": {"title": f"Distribution of {col}"}
            }
        })

    corr_pairs = sorted(corr_pairs, key=lambda x: abs(x["corr"]), reverse=True)[:10]

    outliers = detect_outliers(df)

    return sanitize({
        "meta": meta,
        "summary": summary,
        "corr_pairs": corr_pairs,
        "outliers": outliers,
        "nlg_summary": "AI summary disabled (optional)",
        "raw_data_sample": df.head(50).to_dict("records"),
        "column_names": df.columns.tolist(),
        "figures": figures
    })


# ---------- API ----------
@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):

    filename = file.filename.lower()
    content = await file.read()

    try:
        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content))
            except:
                df = pd.read_csv(io.BytesIO(content), encoding="latin1")

        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))

        else:
            raise HTTPException(400, "Unsupported file type")

        if df.dropna(how='all').empty:
            raise HTTPException(400, "Empty file")

    except Exception as e:
        raise HTTPException(400, str(e))

    return analyze_dataframe(df)


@app.get("/")
def root():
    return {"message": "Backend running 🚀"}