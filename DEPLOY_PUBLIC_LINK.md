# Publish a working ContexA link (Render)

This project has a `render.yaml` Blueprint and a single-container deployment: Render builds the React/Vite frontend and serves it from FastAPI. That gives you one URL for both UI and API; there is no separate Vercel frontend configuration and no Ollama/API key required for the demo.

## 1. Put the source on GitHub

1. Download and extract the `ContexA_Studio_Public_Deploy.zip` archive. The extracted project root already contains `render.yaml`, `backend/`, and `frontend/`.
2. Create an **empty** repository at https://github.com/new (for example `contexa-studio`; do not initialize it with a README).
3. From a terminal opened in the extracted project root, run the commands below, replacing `YOUR_USERNAME` with your GitHub username. You may use GitHub Desktop instead if you prefer.

   ```powershell
   git init
   git add .
   git commit -m "Prepare ContexA for deployment"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/contexa-studio.git
   git push -u origin main
   ```

## 2. Deploy on Render

1. Open https://dashboard.render.com/ and sign in.
2. Choose **New → Blueprint** and connect the `contexa-studio` repository.
3. Render reads `render.yaml`; review the service settings and create the Blueprint.
4. Wait for the build/deploy to succeed. Render will show a public URL similar to `https://contexa-studio-demo.onrender.com`. Use the exact URL shown in your dashboard.
5. Open `<your-url>/api/health`; it should return JSON with `"status":"ok"`. Then open the base URL to try the app.

## Demo access

- Brand Admin: `admin@contexa.local` / `ContexA!2026`
- Manager: `manager@contexa.local` / `Manager!2026`
- SME / Legal: `legal@contexa.local` / `Legal!2026`
- Creator: `creator@contexa.local` / `Creator!2026`

Sign in as Brand Admin and choose **Prepare demo workspace** to create the illustrative sample documents and findings. Deployment sets `APP_ENV=demo`, disables all AI provider calls, and generates a deployment secret. Ollama is not required.

## Important limitations

- This is a public demonstration deployment, not a hardened production environment. Demo credentials are visible in the repository and anyone who visits can sign in with them; do not upload real/confidential documents or personal data.
- The configured SQLite database and uploaded documents use ephemeral container storage. Restart/redeploy can reset demo changes; seed the demo workspace again when needed. For durable production use, attach a persistent disk or configure PostgreSQL and secure authentication.
- Free web services may sleep when idle, causing a delay on the first visit.
- A hosted URL cannot be created by this archive alone; the repository must be connected to your Render account to publish it.
