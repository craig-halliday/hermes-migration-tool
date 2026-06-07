# Hermes Railway Migrator

A small migration utility for moving **Hermes Agent** session history from a hosted Railway/web-dashboard instance into a local Hermes `state.db`.

It is designed for the situation where you can log into the Hermes dashboard but do not have direct shell access to the Railway container.

## What it does

- Provides a browser-console exporter snippet for the Hermes dashboard.
- Imports exported `railway_sessions.json` into a local Hermes SQLite `state.db`.
- Detects the local `sessions` and `messages` schema with `PRAGMA table_info(...)` instead of hard-coding fragile column counts.
- Creates a database backup before writing by default.
- Skips already-imported sessions by session id.
- Verifies imported session/message counts.

## What it does not do

- It does not migrate provider API keys or OAuth tokens. Dashboard UIs usually mask those; re-authenticate locally.
- It does not expose or print secrets.
- It does not require Python web dependencies. Import uses only the Python standard library.

## Install from source

```bash
git clone https://github.com/YOUR_USER/hermes-railway-migrator.git
cd hermes-railway-migrator
python -m pip install -e .
```

Or run directly:

```bash
python -m hermes_railway_migrator --help
```

## Step 1: Export sessions from the hosted Hermes dashboard

1. Open your hosted Hermes dashboard sessions page, for example:

   ```text
   https://your-hermes.example.com/sessions
   ```

2. Log in.
3. Open DevTools Console.
4. Run:

```javascript
(async () => {
  const token = window.__HERMES_SESSION_TOKEN__;
  if (!token) {
    console.error("No session token found. Refresh the /sessions page and try again.");
    return;
  }

  const base = location.origin;
  const headers = { Authorization: "Bearer " + token };

  const sessionsResp = await fetch(base + "/api/sessions", { headers });
  if (!sessionsResp.ok) throw new Error("/api/sessions failed: " + sessionsResp.status);
  const sessionsData = await sessionsResp.json();
  const sessions = sessionsData.sessions || sessionsData || [];

  console.log("Found sessions:", sessions.length);

  const out = [];
  for (const s of sessions) {
    const id = s.id || s.session_id;
    console.log("Fetching", id);

    const [metaResp, messagesResp] = await Promise.all([
      fetch(base + "/api/sessions/" + id, { headers }),
      fetch(base + "/api/sessions/" + id + "/messages", { headers })
    ]);

    if (!metaResp.ok) throw new Error("metadata failed for " + id + ": " + metaResp.status);
    if (!messagesResp.ok) throw new Error("messages failed for " + id + ": " + messagesResp.status);

    const meta = await metaResp.json();
    const messagesData = await messagesResp.json();
    const messages = messagesData.messages || [];

    out.push({ id, meta, messages });
    console.log("OK", id, messages.length, "messages");
  }

  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "railway_sessions.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  console.log("Done. Downloaded railway_sessions.json");
})();
```

## Step 2: Import locally

Windows example:

```bash
python -m hermes_railway_migrator import \
  --input C:/Users/craig/Downloads/railway_sessions.json \
  --db C:/Users/craig/AppData/Local/hermes/state.db
```

Linux/macOS example:

```bash
python -m hermes_railway_migrator import \
  --input ~/Downloads/railway_sessions.json \
  --db ~/.hermes/state.db
```

Dry run first if desired:

```bash
python -m hermes_railway_migrator import --input railway_sessions.json --db ~/.hermes/state.db --dry-run
```

## Verify

```bash
python -m hermes_railway_migrator verify --input railway_sessions.json --db ~/.hermes/state.db
```

You can also use Hermes itself:

```text
session_search("a topic from one of the imported sessions")
```

## Safety

The importer creates a timestamped backup next to your database before writing, unless `--no-backup` is passed.

## License

MIT
