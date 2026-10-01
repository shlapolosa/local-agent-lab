# The VOICEPRINT model — this repo's code, in an image of its own.
#
# Why separate: the model's runtime (PyTorch) is ~1 GB, and every other lab service pulls ONE shared
# image (deploy/Dockerfile). The model runs here instead, beside the substrate, and speech-mcp calls it
# on the private network — the `embedder` precedent. Built by CI on every push (.github/workflows/
# image.yml) as ghcr.io/<repo>/voiceprint:sha-<short>; deployed by `deploy/railway.py substrate up`
# when VOICEPRINT_ENABLED is set. A code `release` does not touch it (topology.is_ours).
#
# Only what the service imports is installed: torch (CPU wheels — there is no GPU, and the CUDA build
# is ~2 GB more), speechbrain, the audio reader, and the HTTP server. The lab's own code is copied in
# whole but only `lab.platform.config`, `lab.substrate.{netbind,mcpauth,voiceprint.service}` load.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 PYTHONPATH=/app/src

# The heavy layer first and on its own: it changes only when these pins do, so a code push rebuilds
# nothing but the last COPY.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio \
 && pip install "speechbrain==1.1.1" soundfile numpy starlette "uvicorn>=0.30"

# The weights, BAKED IN at build time — the model measured on 29 Sep 2026. A container that downloaded
# them at start would depend on Hugging Face being up for every restart, and could silently pull a
# different revision; this one starts offline and is the same model every time.
RUN python -c "from speechbrain.inference.speaker import EncoderClassifier; \
EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir='/models/ecapa', \
run_opts={'device': 'cpu'})"

WORKDIR /app
COPY src/ /app/src/

ARG LAB_BUILD_SHA=""
ENV LAB_BUILD_SHA=${LAB_BUILD_SHA}
EXPOSE 9650
CMD ["python", "-m", "lab.substrate.voiceprint.service"]
