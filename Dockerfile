# ExLex backend: the API, the analysis models and the site, in one image. CPU only.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 EXLEX_DEVICE=cpu
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# the CPU build of PyTorch is far smaller than the default one; install it first so requirements.txt finds it satisfied
COPY backend/requirements.txt backend/requirements.txt
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r backend/requirements.txt

# YOLOv8n, the plate detector and the second reader are in the repository. The CLIP model (577 MB) is not copied: without it body type falls
# back to the detector's class, and everything else works. See DEPLOY.md to add it.
COPY backend backend
COPY deploy/start.sh deploy/start.sh
RUN chmod +x deploy/start.sh

EXPOSE 8000
CMD ["deploy/start.sh"]
