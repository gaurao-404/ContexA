# Build the Vite frontend first, then ship its static assets with FastAPI.
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
ARG VITE_SUBMISSION_MODE=false
ARG VITE_AUTH_MODE=local
ARG VITE_API_URL=
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_PUBLISHABLE_KEY=
ARG VITE_SUPABASE_ANON_KEY=
ENV VITE_SUBMISSION_MODE=${VITE_SUBMISSION_MODE}
ENV VITE_AUTH_MODE=${VITE_AUTH_MODE}
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY}
ENV VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}
COPY frontend/package.json ./package.json
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/bootstrap_supabase_admin.py ./bootstrap_supabase_admin.py
COPY --from=frontend-build /frontend/dist ./static
ENV FRONTEND_DIST_DIR=/app/static
RUN mkdir -p /app/storage
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
