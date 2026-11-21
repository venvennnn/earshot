# Build from the repository root (the backend needs packs/ and knowledge/):
#   docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
# CPU-only PyTorch: the default wheel bundles CUDA and is several GB larger.
RUN pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r backend/requirements.txt

# Bake the CLAP model into the image so startup does not download ~600 MB.
RUN python -c "from transformers import ClapModel, ClapProcessor; m='laion/clap-htsat-unfused'; ClapModel.from_pretrained(m); ClapProcessor.from_pretrained(m)"

COPY packs packs
COPY knowledge knowledge
COPY backend backend
WORKDIR /app/backend

# Railway injects $PORT. Mount a volume at /app/backend/store to keep baselines across deploys.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
