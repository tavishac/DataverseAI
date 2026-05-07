
import React, { useState, useEffect } from "react";
import axios from "axios";
import Plot from "react-plotly.js";

// NOTE: This URL assumes a local FastAPI or similar server is running on port 8000.
// You must ensure your backend server is running and accessible at this address.
const BACKEND_URL = "http://localhost:8000/analyze";

export default function App() {
  const [file, setFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [darkMode, setDarkMode] = useState(false);
  // State to manage the active view: 'input', 'visualizations', or 'analysis'
  const [view, setView] = useState('input'); 
  // State to track the currently displayed chart index for the single-chart view
  const [currentChartIndex, setCurrentChartIndex] = useState(0); 

  // Theme object for managing styling across light/dark modes
  const theme = {
    background: darkMode ? "#0f172a" : "#f5f7fa",
    cardBg: darkMode ? "#1e293b" : "#fff",
    text: darkMode ? "#f8fafc" : "#1f3d7a",
    subtext: darkMode ? "#94a3b8" : "#6c7a89",
    border: darkMode ? "#334155" : "#e5e7eb",
    inputBg: darkMode ? "#1e293b" : "#f8f9fa",
    primary: darkMode ? "#38bdf8" : "#1f78c1"
  };

  // Handler for uploading the file and triggering analysis
  const upload = async () => {
    if (!file) {
      setError("Please select a file first.");
      return;
    }

    const fd = new FormData();
    fd.append("file", file);
    
    setLoading(true);
    setError(null);
    setAnalysis(null);
    setCurrentChartIndex(0); // Reset chart index on new upload
    
    // Switch to the Analysis tab while the file is processing
    setView('analysis'); 

    try {
      const res = await axios.post(BACKEND_URL, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      
      setAnalysis(res.data);
      // After success, switch to the Visualizations tab
      setView('visualizations'); 
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message || "An unknown error occurred during analysis.";
      setError(`Backend Error: ${detail}. Please ensure the server is running at ${BACKEND_URL}.`);
      setView('input'); // Switch back to input on error
    } finally {
      setLoading(false);
    }
  };

  // Effect to reset chart index whenever new analysis results are loaded
  useEffect(() => {
    if (analysis && analysis.figures.length > 0) {
        setCurrentChartIndex(0);
    }
  }, [analysis]);
  
  // Navigation Handlers
  const handleNext = () => {
    if (analysis && analysis.figures.length > 0) {
        setCurrentChartIndex(prev => (prev + 1) % analysis.figures.length);
    }
  };

  const handlePrev = () => {
    if (analysis && analysis.figures.length > 0) {
        // Use modulo to wrap around to the last index if current is 0
        setCurrentChartIndex(prev => (prev - 1 + analysis.figures.length) % analysis.figures.length);
    }
  };


  // Effect to set global body styles based on the theme
  useEffect(() => {
    document.body.style.backgroundColor = theme.background;
    document.body.style.fontFamily =
      "'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif";
    document.body.style.color = theme.text;
  }, [darkMode, theme.background, theme.text]);

  // Reusable component for section cards
  const Card = ({ title, children, style = {} }) => (
    <div
      style={{
        background: theme.cardBg,
        padding: "25px",
        borderRadius: "14px",
        boxShadow: darkMode
          ? "0 0 15px rgba(0,0,0,0.4)"
          : "0 8px 24px rgba(0, 0, 0, 0.05)",
        marginBottom: "30px",
        transition: "all 0.3s ease",
        border: `1px solid ${theme.border}`,
        ...style
      }}
    >
      <h3
        style={{
          borderBottom: `2px solid ${theme.primary}`,
          paddingBottom: "10px",
          marginBottom: "20px",
          color: theme.text,
          fontSize: "1.5em",
          fontWeight: 600,
        }}
      >
        {title}
      </h3>
      {children}
    </div>
  );

  // Reusable component for error messages
  const Alert = ({ children }) => (
    <div
      style={{
        backgroundColor: darkMode ? "#440e0e" : "#fdecea",
        color: darkMode ? "#fff" : "#c0392b",
        padding: "12px",
        borderRadius: "6px",
        marginTop: "15px",
        fontWeight: 500,
      }}
    >
      {children}
    </div>
  );

  // Reusable component for the data table
  const StyledTable = ({ children }) => (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontSize: "0.95em",
        color: theme.text,
      }}
    >
      {children}
    </table>
  );

  // Reusable component for table headers
  const StyledTh = ({ children, isLetterRow = false, style = {} }) => (
    <th
      style={{
        backgroundColor: isLetterRow ? (darkMode ? '#0f172a' : '#e2e8f0') : (darkMode ? "#1e293b" : "#f1f5fa"),
        padding: "12px 15px",
        textAlign: "left",
        color: isLetterRow ? theme.subtext : theme.text,
        borderBottom: isLetterRow ? 'none' : `1px solid ${theme.border}`,
        position: 'sticky', // Make header row sticky for scrolling
        top: isLetterRow ? 0 : '38px',
        zIndex: 10,
        ...style,
      }}
    >
      {children}
    </th>
  );

  // Reusable component for table data cells
  const StyledTd = ({ children, style = {} }) => (
    <td
      style={{
        padding: "10px 15px",
        textAlign: "left",
        borderBottom: `1px solid ${theme.border}`,
        backgroundColor: theme.cardBg, 
        ...style,
      }}
    >
      {children}
    </td>
  );
  
  // Component for displaying raw data sample, mimicking a spreadsheet view
  const RawDataView = ({ data, columns }) => {
    if (!data || data.length === 0) return <p style={{ color: theme.subtext, padding: '20px' }}>No data sample available. Upload a file to see a preview here.</p>;

    const maxColumns = 10; // Limit columns for visual display
    const displayColumns = columns.slice(0, maxColumns);
    const hasMoreColumns = columns.length > maxColumns;
    
    // Generate headers with letters (A, B, C...)
    const tableHeaders = displayColumns.map((col, index) => ({
      letter: String.fromCharCode(65 + index), 
      name: col 
    }));

    return (
      <div 
        style={{ 
          overflow: "auto", 
          maxHeight: '70vh', 
          background: theme.cardBg, 
          borderRadius: '6px',
          border: `1px solid ${theme.border}`,
          boxShadow: darkMode ? "inset 0 0 10px rgba(0,0,0,0.2)" : "inset 0 0 10px rgba(0,0,0,0.05)"
        }}
      >
        <StyledTable>
          <thead style={{ position: 'sticky', top: 0, zIndex: 11 }}>
            {/* Row 1: Column Letters (A, B, C...) - Sticky */}
            <tr style={{ position: 'sticky', top: 0, zIndex: 11 }}>
              <StyledTh isLetterRow={true} style={{ minWidth: '60px', left: 0, position: 'sticky' }}>#</StyledTh> 
              {tableHeaders.map((header) => (
                <StyledTh key={`letter-${header.letter}`} isLetterRow={true} style={{ fontSize: '0.8em', fontWeight: 500 }}>
                  {header.letter}
                </StyledTh>
              ))}
              {hasMoreColumns && <StyledTh isLetterRow={true} style={{ fontSize: '0.8em', fontWeight: 500 }}>...</StyledTh>}
            </tr>
            {/* Row 2: Column Names - Sticky */}
            <tr style={{ position: 'sticky', top: '38px', zIndex: 11 }}>
              <StyledTh style={{ fontWeight: 600, minWidth: '60px', left: 0, position: 'sticky', backgroundColor: darkMode ? "#1e293b" : "#f1f5fa" }}>Row ID</StyledTh>
              {tableHeaders.map((header) => (
                <StyledTh key={`name-${header.name}`} style={{ fontWeight: 600, minWidth: '120px' }}>
                  {header.name}
                </StyledTh>
              ))}
              {hasMoreColumns && <StyledTh style={{ fontWeight: 600, minWidth: '50px' }}>+{columns.length - maxColumns} more</StyledTh>}
            </tr>
          </thead>
          <tbody>
            {/* Display data rows */}
            {data.map((row, rowIndex) => (
                <tr key={rowIndex}>
                    <StyledTd style={{ fontWeight: 600, left: 0, position: 'sticky', backgroundColor: theme.cardBg }}>{rowIndex + 1}</StyledTd>
                    {displayColumns.map((colName, colIndex) => (
                        <StyledTd key={`${rowIndex}-${colIndex}`}>
                            {row[colName] !== null && row[colName] !== undefined ? String(row[colName]) : <span style={{ color: theme.subtext, opacity: 0.6 }}>--</span>}
                        </StyledTd>
                    ))}
                    {hasMoreColumns && <StyledTd>...</StyledTd>}
                </tr>
            ))}
          </tbody>
        </StyledTable>
      </div>
    );
  };

  return (
    <div
      style={{
        padding: 30,
        maxWidth: 1400,
        margin: "0 auto",
        minHeight: "100vh",
      }}
    >
      <header
        style={{
          textAlign: "center",
          marginBottom: "40px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <h1
          style={{
            color: theme.text,
            fontSize: "2.8em",
            fontWeight: 700,
            margin: 0,
          }}
        >
            Dataverse AI
        </h1>
        <button
          onClick={() => setDarkMode((prev) => !prev)}
          style={{
            padding: "10px 16px",
            background: darkMode ? "#334155" : theme.primary,
            color: "#fff",
            border: "none",
            borderRadius: "6px",
            cursor: "pointer",
            fontWeight: 500,
            transition: "background-color 0.3s ease",
          }}
        >
          {darkMode ? "☀️ Light Mode" : "🌙 Dark Mode"}
        </button>
      </header>

      {/* Main Tabbed Interface */}
      <div style={{ padding: "20px", borderRadius: "14px", background: theme.cardBg, border: `1px solid ${theme.border}`, boxShadow: darkMode ? "0 0 15px rgba(0,0,0,0.4)" : "0 8px 24px rgba(0, 0, 0, 0.05)", }}>
        <div style={{ display: 'flex', borderBottom: `2px solid ${theme.border}`, marginBottom: '20px' }}>
            {/* Tab 1: Input Data */}
            <button
                onClick={() => setView('input')}
                style={{
                    padding: "10px 20px",
                    cursor: "pointer",
                    fontWeight: 600,
                    border: 'none',
                    borderBottom: view === 'input' ? `3px solid ${theme.primary}` : '3px solid transparent',
                    background: 'none',
                    color: view === 'input' ? theme.text : theme.subtext,
                    transition: 'color 0.3s',
                }}
            >
                Input Data
            </button>

            {/* Tab 2: Analysis (Report) */}
            <button
                onClick={() => setView('analysis')}
                disabled={!analysis && !loading} 
                style={{
                    padding: "10px 20px",
                    cursor: (analysis || loading) ? "pointer" : "not-allowed",
                    fontWeight: 600,
                    border: 'none',
                    borderBottom: view === 'analysis' ? `3px solid ${theme.primary}` : '3px solid transparent',
                    background: 'none',
                    color: view === 'analysis' ? theme.text : theme.subtext,
                    transition: 'color 0.3s',
                    opacity: (analysis || loading) ? 1 : 0.5,
                }}
            >
                Analysis (Report)
            </button>
            
            {/* Tab 3: Visualizations */}
            <button
                onClick={() => setView('visualizations')}
                disabled={!analysis && !loading} 
                style={{
                    padding: "10px 20px",
                    cursor: (analysis || loading) ? "pointer" : "not-allowed",
                    fontWeight: 600,
                    border: 'none',
                    borderBottom: view === 'visualizations' ? `3px solid ${theme.primary}` : '3px solid transparent',
                    background: 'none',
                    color: view === 'visualizations' ? theme.text : theme.subtext,
                    transition: 'color 0.3s',
                    opacity: (analysis || loading) ? 1 : 0.5,
                }}
            >
                Visualizations
            </button>
        </div>
        
        {/* === LOADING STATE FOR ALL ANALYSIS/VISUALIZATION VIEWS === */}
        {(view === 'analysis' || view === 'visualizations') && loading && (
            <p style={{ color: theme.subtext, padding: '50px', textAlign: 'center', fontSize: '1.1em' }}>
              <span role="img" aria-label="loading" style={{fontSize: '2em', display: 'block', marginBottom: '10px'}}>⚙️</span>
              Processing file and generating report. This may take a moment...
            </p>
        )}
        
        {/* === FALLBACK IF NOT ANALYZED === */}
        {(view === 'analysis' || view === 'visualizations') && !analysis && !loading && (
            <p style={{ color: theme.subtext, padding: '20px', textAlign: 'center' }}>Upload a file in the **Input Data** tab and click 'Upload & Analyze' to view the analysis.</p>
        )}

        {/* === INPUT DATA VIEW CONTENT === */}
        {view === 'input' && (
            <>
                <div style={{ display: "flex", gap: "20px", alignItems: "center", flexWrap: 'wrap', marginBottom: '20px' }}>
                    <input
                        type="file"
                        accept=".xlsx,.xls,.csv"
                        onChange={(e) => {
                            setFile(e.target.files[0]);
                            setAnalysis(null);
                            setError(null);
                        }}
                        style={{
                            padding: "10px",
                            border: `1px solid ${theme.border}`,
                            borderRadius: "6px",
                            background: theme.inputBg,
                            color: theme.text,
                            flexGrow: 1,
                            minWidth: '200px'
                        }}
                    />
                    <button
                        onClick={upload}
                        disabled={loading || !file}
                        style={{
                            padding: "10px 20px",
                            backgroundColor: theme.primary,
                            color: "#fff",
                            border: "none",
                            borderRadius: "6px",
                            cursor: loading || !file ? "not-allowed" : "pointer",
                            fontWeight: 500,
                            opacity: loading || !file ? 0.7 : 1,
                            transition: "opacity 0.3s ease, background-color 0.3s ease",
                        }}
                    >
                        {loading ? "Analyzing..." : "Upload & Analyze"}
                    </button>
                </div>
                {error && <Alert>{error}</Alert>}
                
                {/* Display the raw data sample after a successful analysis */}
                <h2 style={{ fontSize: '1.4em', fontWeight: 600, color: theme.text, marginTop: '20px', marginBottom: '10px' }}>
                    {analysis ? `Previewing Data Sample (${analysis.column_names.length} columns, showing first 50 rows)` : "Data Preview (Upload a file to see a sample)"}
                </h2>
                {analysis && analysis.raw_data_sample ? (
                    <RawDataView 
                        data={analysis.raw_data_sample} 
                        columns={analysis.column_names} 
                    />
                ) : (
                    <div style={{ padding: '20px', border: `1px solid ${theme.border}`, borderRadius: '6px', backgroundColor: theme.inputBg }}>
                        <p style={{ color: theme.subtext, textAlign: 'center' }}>
                            {file ? `File selected: ${file.name}. Click 'Upload & Analyze' to process and see the preview.` : "No file uploaded yet. Only .xlsx, .xls, and .csv files are supported."}
                        </p>
                    </div>
                )}
            </>
        )}
        
        {/* --- VISUALIZATIONS VIEW CONTENT (Single Chart + Navigation) --- */}
        {view === 'visualizations' && analysis && (
            <>
                {analysis.figures.length > 0 ? (
                    <Card 
                        title={`Visualizations (${currentChartIndex + 1} of ${analysis.figures.length})`} 
                        style={{ marginBottom: 0 }}
                    >
                        {/* Container for the single chart and navigation buttons */}
                        <div 
                            style={{ 
                                display: 'flex', 
                                alignItems: 'center', 
                                justifyContent: 'center', 
                                position: 'relative',
                                minHeight: '550px', // Ensure min height for better layout
                                background: theme.cardBg, // Chart container background
                                borderRadius: '8px',
                                border: `1px solid ${theme.border}`,
                            }}
                        >
                            {/* Previous Button */}
                            <button
                                onClick={handlePrev}
                                disabled={analysis.figures.length <= 1}
                                style={{
                                    position: 'absolute',
                                    left: '10px',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    zIndex: 20,
                                    padding: '15px 5px',
                                    borderRadius: '50%',
                                    background: 'rgba(0,0,0,0.6)',
                                    color: 'white',
                                    border: 'none',
                                    cursor: analysis.figures.length <= 1 ? 'not-allowed' : 'pointer',
                                    opacity: analysis.figures.length <= 1 ? 0.3 : 1,
                                    fontSize: '24px',
                                    lineHeight: 0,
                                    transition: 'background 0.2s',
                                    boxShadow: '0 2px 5px rgba(0,0,0,0.3)'
                                }}
                            >
                                &#9664; {/* Left arrow */}
                            </button>

                            {/* Current Plot Rendering */}
                            {analysis.figures[currentChartIndex] && (
                                <div 
                                    key={analysis.figures[currentChartIndex].id}
                                    style={{
                                        width: "90%", // Limit plot width slightly to make room for arrows
                                        maxWidth: 800, 
                                        height: 'auto',
                                        transition: 'opacity 0.3s ease',
                                    }}
                                >
                                    <Plot
                                        data={analysis.figures[currentChartIndex].figure.data || []}
                                        layout={{
                                            ...analysis.figures[currentChartIndex].figure.layout,
                                            autosize: true,
                                            paper_bgcolor: theme.cardBg,
                                            plot_bgcolor: theme.cardBg,
                                            font: { color: theme.text },
                                            margin: { t: 50, b: 50, l: 50, r: 20 },
                                        }}
                                        config={{ 
                                            ...analysis.figures[currentChartIndex].figure.config,
                                            responsive: true 
                                        }}
                                        style={{
                                            width: "100%",
                                            // Adjust height based on plot type, or use a default
                                            height: analysis.figures[currentChartIndex].id === "heatmap_corr" ? 550 : 450, 
                                        }}
                                    />
                                </div>
                            )}
                            
                            {/* Next Button */}
                            <button
                                onClick={handleNext}
                                disabled={analysis.figures.length <= 1}
                                style={{
                                    position: 'absolute',
                                    right: '10px',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    zIndex: 20,
                                    padding: '15px 5px',
                                    borderRadius: '50%',
                                    background: 'rgba(0,0,0,0.6)',
                                    color: 'white',
                                    border: 'none',
                                    cursor: analysis.figures.length <= 1 ? 'not-allowed' : 'pointer',
                                    opacity: analysis.figures.length <= 1 ? 0.3 : 1,
                                    fontSize: '24px',
                                    lineHeight: 0,
                                    transition: 'background 0.2s',
                                    boxShadow: '0 2px 5px rgba(0,0,0,0.3)'
                                }}
                            >
                                &#9654; {/* Right arrow */}
                            </button>
                        </div>
                        
                    </Card>
                ) : (
                    <p style={{ color: theme.subtext, padding: '20px', textAlign: 'center' }}>No visualizations could be generated, likely due to insufficient numeric or categorical data.</p>
                )}
            </>
        )}


        {/* === ANALYSIS (REPORT) VIEW CONTENT === */}
        {view === 'analysis' && analysis && (
            <>
              {/* 1. Dataset Overview Table (Full Width) */}
              <Card title="1. Dataset Overview">
                <p style={{ fontWeight: 500, color: theme.text, marginBottom: '15px' }}>
                  Dataset has <strong>{analysis.meta.rows}</strong> rows and{" "}
                  <strong>{analysis.meta.cols}</strong> columns.
                </p>
                <div style={{ overflowX: "auto" }}>
                  <StyledTable>
                    <thead>
                      <tr>
                        <StyledTh style={{position: 'relative', top: 'unset'}}>Name</StyledTh>
                        <StyledTh style={{position: 'relative', top: 'unset'}}>Dtype</StyledTh>
                        <StyledTh style={{position: 'relative', top: 'unset'}}>Missing (%)</StyledTh>
                        <StyledTh style={{position: 'relative', top: 'unset'}}>Unique Values</StyledTh>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.meta.columns.map((col, i) => {
                        const missingPercent = ((col.missing / analysis.meta.rows) * 100);
                        return (
                          <tr key={i}>
                            <StyledTd>{col.name}</StyledTd>
                            <StyledTd>{col.dtype}</StyledTd>
                            <StyledTd 
                              style={{
                                // Highlight columns with high missing percentages
                                backgroundColor: missingPercent > 50 
                                  ? (darkMode ? '#440e0e' : '#ffeeee') 
                                  : theme.cardBg,
                                color: missingPercent > 50 
                                  ? (darkMode ? '#fef2f2' : '#c0392b') 
                                  : theme.text,
                                fontWeight: missingPercent > 0 ? 600 : 500
                              }}
                            >
                              {missingPercent.toFixed(1)}%
                            </StyledTd>
                            <StyledTd>{col.unique}</StyledTd>
                          </tr>
                        );
                      })}
                    </tbody>
                  </StyledTable>
                </div>
              </Card>

              {/* 2. AI-Powered Analysis Summary (Full Width) */}
              
            </>
        )}
      </div>
    </div>
  );
}
