# ContexA Round 3 — Quick Start

## Local demonstration

1. Extract this project into a new folder.
2. On Windows, run `run-submission.bat`; on macOS/Linux, run `./run-submission.sh`.
3. Open `http://localhost:5173` after the frontend and backend report ready.
4. Sign in using the demo account documented in `SUBMISSION_GUIDE.md` or create a separate workspace account if public signup is enabled.
5. Upload the fictional approved price book in Content.
6. Open Insights → Brand Intelligence Lab and add an approved fact linked to that document. Paste an exact supporting quotation.
7. Approve the fact, upload marketing copy with a deliberately old price, and inspect its finding evidence.
8. Use the policy simulator and deterministic benchmark to demonstrate policy impact and measured results.

Submission Mode disables Ollama/cloud AI. It exercises the deterministic workflow. Local AI can be enabled separately for development when Ollama is installed and configured.

## Run tests

```bash
cd backend
python -m pip install -r requirements.txt
python -m pytest -q
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The current test suite has 38 backend tests. Python compilation and TypeScript/TSX syntax checks pass. A full Vite production build was not completed in this environment because npm dependency installation timed out. Run `npm install` and `npm run build` from `frontend/` before deploying.
