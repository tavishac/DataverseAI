import React, { useState, useEffect } from "react";
import axios from "axios";
import Plot from "react-plotly.js";
import { motion, AnimatePresence } from "framer-motion";

const BACKEND_URL = "http://localhost:8000/analyze";

export default function App() {
  const [file, setFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [darkMode, setDarkMode] = useState(false);
  const [view, setView] = useState("input");
  const [currentChartIndex, setCurrentChartIndex] = useState(0);

  const theme = {
    background: darkMode ? "#0f172a" : "#f5f7fa",
    cardBg: darkMode ? "#1e293b" : "#fff",
    text: darkMode ? "#f8fafc" : "#1f3d7a",
    subtext: darkMode ? "#94a3b8" : "#6c7a89",
    border: darkMode ? "#334155" : "#e5e7eb",
    inputBg: darkMode ? "#1e293b" : "#f8f9fa",
    primary: darkMode ? "#38bdf8" : "#1f78c1",
  };

  const upload = async () => {
    if (!file) {
      setError("Please select a file first.");
      return;
    }

    const fd = new FormData();
    fd.append("file", file);
    setError(null);
    setLoading(true);
    setAnalysis(null);
    setCurrentChartIndex(0);
    setView("analysis");

    try {
      const res = await axios.post(BACKEND_URL, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setAnalysis(res.data);
      setView("visualizations");
    } catch (err) {
      setError(
        `Backend Error: ${
          err?.response?.data?.detail || err.message
        }. Check server status.`
      );
      setView("input");
    } finally {
      setLoading(false);
    }
  };

  const nextChart = () => {
    if (!analysis?.figures?.length) return;
    setCurrentChartIndex((i) => (i + 1) % analysis.figures.length);
  };

  const prevChart = () => {
    if (!analysis?.figures?.length) return;
    setCurrentChartIndex(
      (i) => (i - 1 + analysis.figures.length) % analysis.figures.length
    );
  };

  useEffect(() => {
    document.body.style.backgroundColor = theme.background;
    document.body.style.color = theme.text;
  }, [darkMode]);

  const fade = {
    hidden: { opacity: 0, y: 15 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
    exit: { opacity: 0, y: -10, transition: { duration: 0.3 } },
  };

  const Card = ({ title, children }) => (
    <motion.div
      variants={fade}
      initial="hidden"
      animate="visible"
      style={{
        background: theme.cardBg,
        padding: 25,
        borderRadius: 14,
        border: `1px solid ${theme.border}`,
        boxShadow: darkMode
          ? "0 0 15px rgba(0,0,0,0.4)"
          : "0 8px 24px rgba(0,0,0,0.05)",
        marginBottom: 30,
      }}
    >
      <h3
        style={{
          borderBottom: `2px solid ${theme.primary}`,
          paddingBottom: 10,
          marginBottom: 20,
          color: theme.text,
          fontSize: "1.5em",
          fontWeight: 600,
        }}
      >
        {title}
      </h3>
      {children}
    </motion.div>
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6 }}
      style={{
        padding: 30,
        maxWidth: 1400,
        margin: "0 auto",
        minHeight: "100vh",
      }}
    >
      {/* Header */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 40,
          flexWrap: "wrap",
        }}
      >
        <motion.h1
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={{
            fontSize: "2.8em",
            fontWeight: 700,
            color: theme.text,
            margin: 0,
          }}
        >
          Dataverse AI
        </motion.h1>
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={() => setDarkMode((p) => !p)}
          style={{
            padding: "10px 16px",
            background: darkMode ? "#334155" : theme.primary,
            color: "#fff",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
            fontWeight: 500,
          }}
        >
          {darkMode ? "☀️ Light Mode" : "🌙 Dark Mode"}
        </motion.button>
      </header>

      {/* Tabs */}
      <motion.div
        style={{
          background: theme.cardBg,
          border: `1px solid ${theme.border}`,
          borderRadius: 14,
          padding: 20,
          boxShadow: darkMode
            ? "0 0 15px rgba(0,0,0,0.4)"
            : "0 8px 24px rgba(0, 0, 0, 0.05)",
        }}
      >
        <div style={{ display: "flex", marginBottom: 20 }}>
          {["input", "analysis", "visualizations"].map((tab) => (
            <motion.button
              key={tab}
              onClick={() => setView(tab)}
              whileHover={{ scale: 1.02 }}
              style={{
                padding: "10px 20px",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
                background: "none",
                borderBottom:
                  view === tab
                    ? `3px solid ${theme.primary}`
                    : "3px solid transparent",
                color: view === tab ? theme.text : theme.subtext,
                transition: "0.3s",
              }}
            >
              {tab === "input"
                ? "Input Data"
                : tab === "analysis"
                ? "Summary"
                : "Visualizations"}
            </motion.button>
          ))}
        </div>

        {/* Content */}
        <AnimatePresence mode="wait">
          {loading && (
            <motion.div
              key="loading"
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
              style={{
                textAlign: "center",
                padding: 80,
                color: theme.subtext,
                fontSize: "1.2em",
              }}
            >
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
                style={{
                  fontSize: "2.5em",
                  marginBottom: 10,
                  display: "inline-block",
                }}
              >
                ⚙️
              </motion.div>
              <div>Processing your data...</div>
            </motion.div>
          )}

          {!loading && view === "input" && (
            <motion.div
              key="input"
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <Card title="Upload Your Dataset">
                <div
                  style={{
                    display: "flex",
                    gap: 15,
                    alignItems: "center",
                    flexWrap: "wrap",
                    marginBottom: 20,
                  }}
                >
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={(e) => {
                      setFile(e.target.files[0]);
                      setError(null);
                    }}
                    style={{
                      padding: 10,
                      border: `1px solid ${theme.border}`,
                      borderRadius: 6,
                      background: theme.inputBg,
                      color: theme.text,
                      flexGrow: 1,
                      minWidth: 200,
                    }}
                  />
                  <motion.button
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    onClick={upload}
                    disabled={!file || loading}
                    style={{
                      padding: "10px 20px",
                      background: theme.primary,
                      color: "#fff",
                      border: "none",
                      borderRadius: 8,
                      cursor: !file ? "not-allowed" : "pointer",
                      opacity: !file ? 0.6 : 1,
                      fontWeight: 500,
                    }}
                  >
                    {loading ? "Analyzing..." : "Upload & Analyze"}
                  </motion.button>
                </div>
                {error && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    style={{
                      background: darkMode ? "#450a0a" : "#fdecea",
                      color: darkMode ? "#fff" : "#c0392b",
                      padding: 12,
                      borderRadius: 6,
                      marginTop: 10,
                    }}
                  >
                    {error}
                  </motion.div>
                )}
              </Card>
            </motion.div>
          )}

          {!loading && view === "analysis" && analysis && (
            <motion.div
              key="analysis"
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <Card title="AI Summary">
                <div
                  style={{
                    color: theme.text,
                    lineHeight: 1.8,
                    whiteSpace: "pre-wrap",
                  }}
                  dangerouslySetInnerHTML={{
                    __html: analysis?.nlg_summary?.replace(/\n/g, "<br/>"),
                  }}
                />
              </Card>
            </motion.div>
          )}

          {!loading && view === "visualizations" && analysis?.figures && (
            <motion.div
              key="visual"
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <Card
                title={`Visualization ${currentChartIndex + 1} of ${
                  analysis.figures.length
                }`}
              >
                <Plot
                  data={analysis.figures[currentChartIndex].figure.data}
                  layout={{
                    ...analysis.figures[currentChartIndex].figure.layout,
                    paper_bgcolor: theme.cardBg,
                    plot_bgcolor: theme.cardBg,
                    font: { color: theme.text },
                  }}
                  config={{ responsive: true }}
                  style={{ width: "100%", height: 500 }}
                />
                <div
                  style={{
                    marginTop: 20,
                    display: "flex",
                    justifyContent: "space-between",
                  }}
                >
                  <button
                    onClick={prevChart}
                    style={{
                      background: theme.primary,
                      color: "#fff",
                      padding: "10px 20px",
                      border: "none",
                      borderRadius: 6,
                      cursor: "pointer",
                    }}
                  >
                    ⬅ Prev
                  </button>
                  <button
                    onClick={nextChart}
                    style={{
                      background: theme.primary,
                      color: "#fff",
                      padding: "10px 20px",
                      border: "none",
                      borderRadius: 6,
                      cursor: "pointer",
                    }}
                  >
                    Next ➡
                  </button>
                </div>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  );
}
