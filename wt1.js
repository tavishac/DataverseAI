const express = require("express");
const session = require("express-session");

const app = express(); // ✅ this creates an Express app

app.use(session({
  secret: "mySecretKey",        // used to sign the session ID cookie
  resave: false,                // don’t save if nothing changed
  saveUninitialized: true,      // save new but empty sessions
}));

app.get("/login", (req, res) => {
  req.session.username = "Juhi";
  res.send("Session started for Juhi!");
});

app.get("/profile", (req, res) => {
  res.send(`Logged in user: ${req.session.username}`);
});

app.listen(3000, () => {
  console.log("Server running at http://localhost:3000");
});
