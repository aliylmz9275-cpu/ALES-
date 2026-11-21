# ALES Cloud - cok asamali build
# 1. asama: React/Vite frontend'i derle (cikti ALES/dist/ klasorune duser,
#    vite.config.js'deki outDir ayari geregi)
# 2. asama: Python backend + derlenmis frontend'i TEK image'da birlestir

# ─── ASAMA 1: FRONTEND BUILD ───────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# ─── ASAMA 2: PYTHON BACKEND + STATIK FRONTEND ────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY railway/requirements_cloud.txt ./railway/requirements_cloud.txt
RUN pip install --no-cache-dir -r railway/requirements_cloud.txt

COPY backend/ ./backend/
COPY railway/ ./railway/

COPY --from=frontend-build /build/dist ./dist

ENV PORT=10000
EXPOSE 10000

CMD ["python", "railway/main_cloud.py"]
