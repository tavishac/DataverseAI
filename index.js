const express = require('express');
const app = express();
const PORT = 3000;

// ✅ 1️⃣ Middleware for specific path
app.use('/admin', (req, res, next) => {
  console.log('🛡️ Admin middleware executed');
  next();
});

// ✅ 2️⃣ Static Route
app.get('/', (req, res) => {
  res.send('🏠 Welcome to Home Page!');
});

// ✅ 3️⃣ Dynamic Route
app.get('/user/:id', (req, res) => {
  res.send(`👤 User ID: ${req.params.id}`);
});

// ✅ 4️⃣ Optional Parameter (Express 5–compatible way)
// Instead of '/item/:id?', define both routes
app.get(['/item', '/item/:id'], (req, res) => {
  if (req.params.id) {
    res.send(`📦 Item ID: ${req.params.id}`);
  } else {
    res.send('📦 No item specified');
  }
});

// ✅ 5️⃣ Query Parameter
app.get('/search', (req, res) => {
  const { q } = req.query;
  res.send(`🔎 You searched for: ${q}`);
});

// ✅ 6️⃣ Regex Routes
// Matches any path containing 'hello'
app.get(/hello/, (req, res) => {
  res.send('👋 Route contains "hello"');
});

// Matches routes ending with 'fly'
app.get(/.*fly$/, (req, res) => {
  res.send('🦋 Matched a route ending with "fly"');
});

// ✅ 7️⃣ Admin Route (with middleware)
app.get('/admin', (req, res) => {
  res.send('🔐 Admin Panel Accessed');
});

app.listen(PORT, () => console.log(`✅ Server running on http://localhost:${PORT}`));
