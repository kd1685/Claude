// ---- Kingdom 1685 site configuration ----
// The website talks to the tracker backend's REST API.
//
// • Served from your VPS (the normal setup): leave this "". The site and API
//   are the same origin, so everything just works.
//
// • Hosting the website somewhere separate (e.g. a static host) and pointing it
//   at a remote backend: set this to that backend's public URL, e.g.
//   "https://rok.example.com", and set CORS_ORIGINS on the backend.
window.API_BASE = "";
