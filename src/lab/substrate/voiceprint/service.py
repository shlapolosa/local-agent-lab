"""voiceprint — the speaker-embedding MODEL as a service (port 9650).

POST /embed   {"clips": ["<base64 16 kHz mono WAV>", ...]}  ->  {"model": "...", "vectors": [[...], ...]}
GET  /healthz ->  {"model": "..."}

WHY A SERVICE OF ITS OWN. The model's runtime is ~1 GB, and every other lab service pulls ONE shared
image. So the model runs here, in its own image, beside the substrate — the `embedder` precedent — and
speech-mcp (which already holds the audio) calls it on the private network.

WHAT IT HOLDS: the model and nothing else. No store, no bucket, no gallery, no provider credential; the
only secret is the shared bearer every substrate service checks. It returns vectors, which are biometric
data, so it answers only a caller presenting that secret, and it logs counts — never a clip, never a
vector. Run: `python -m lab.substrate.voiceprint.service` (needs the voiceprint image's dependencies).
"""
from __future__ import annotations

import base64
import binascii
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lab.platform import config
from lab.substrate import netbind
from lab.substrate.mcpauth import BearerAuthMiddleware

SERVICE = "voiceprint"
MAX_CLIPS = 400                      # a two-hour meeting's segments, comfortably
MAX_BODY_BYTES = 64 * 1024 * 1024    # ~30 min of 16 kHz mono PCM, base64-encoded

# The model, named WITH its source: a vector compares only with vectors from exactly this model, so the
# id is stored beside every voiceprint and a changed model can never be silently compared.
MODEL_ID = "ecapa-voxceleb/speechbrain"
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


MAX_THREADS = 4     # past this an ECAPA forward pass on CPU stops getting faster


def cpu_threads(override: str = "", read=None, host_cores: int | None = None) -> int:
    """How many threads the model may use — the container's CPU QUOTA, not the host's core count.

    PyTorch sizes its thread pool from `os.cpu_count()`, which inside a container is the HOST's cores.
    With a CPU quota of one or two vCPUs, dozens of threads then fight over that quota and are throttled
    in turn. Measured 1 Oct 2026 on Railway: one embedding call that takes seconds on a laptop took ~6
    minutes there, past every timeout in the chain. So the quota is read from the cgroup (v2
    `cpu.max`, else v1 `cpu.cfs_quota_us`/`cpu.cfs_period_us`), capped, and overridable."""
    import os
    if (override or "").strip().isdigit() and int(override) > 0:
        return int(override)

    def _read(path):
        try:
            return (read or (lambda p: open(p).read()))(path).strip()
        except OSError:
            return ""

    quota = None
    v2 = _read("/sys/fs/cgroup/cpu.max").split()
    if len(v2) == 2 and v2[0] != "max":
        quota = int(v2[0]) / int(v2[1])
    else:
        q, p = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q.lstrip("-").isdigit() and p.isdigit() and int(q) > 0:
            quota = int(q) / int(p)
    cores = quota if quota else (host_cores if host_cores is not None else (os.cpu_count() or 1))
    return max(1, min(MAX_THREADS, int(cores)))


class EcapaEmbedder:
    """ECAPA-TDNN via speechbrain — the model measured on 29 Sep 2026. Imported lazily, so this module
    loads (and its tests run) without PyTorch; only the voiceprint image installs it."""

    model = MODEL_ID

    def __init__(self, savedir: str = "/models/ecapa", threads: int | None = None) -> None:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        self.threads = threads or cpu_threads(config.VOICEPRINT_THREADS)
        torch.set_num_threads(self.threads)
        self._enc = EncoderClassifier.from_hparams(source=MODEL_SOURCE, savedir=savedir,
                                                   run_opts={"device": "cpu"})

    def embed(self, clips) -> list[tuple[float, ...]]:
        import io

        import numpy as np
        import soundfile as sf
        import torch
        out = []
        for wav in clips:
            audio, rate = sf.read(io.BytesIO(wav), dtype="float32")
            if rate != 16000 or getattr(audio, "ndim", 1) != 1:
                raise ValueError(f"clips must be 16 kHz mono WAV (got {rate} Hz, {audio.ndim} channels)")
            with torch.no_grad():
                v = self._enc.encode_batch(torch.tensor(audio).unsqueeze(0)).squeeze().numpy()
            out.append(tuple(float(x) for x in v / np.linalg.norm(v)))
        return out


def app_for(embedder) -> Starlette:
    """The HTTP surface around ANY `SpeakerEmbedder` — injected, so tests use a fake model."""

    async def embed(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse({"error": f"the request is larger than {MAX_BODY_BYTES} bytes"}, 413)
        try:
            import json
            clips = [base64.b64decode(c, validate=True) for c in json.loads(raw or b"{}").get("clips") or []]
        except (ValueError, binascii.Error, AttributeError, TypeError) as e:
            return JSONResponse({"error": f"the body must be {{\"clips\": [base64 WAV, ...]}}: {e}"}, 400)
        if not clips:
            return JSONResponse({"error": "no clips to embed"}, 400)
        if len(clips) > MAX_CLIPS:
            return JSONResponse({"error": f"{len(clips)} clips is more than the {MAX_CLIPS} one call may embed"}, 413)
        started = time.monotonic()
        try:
            vectors = embedder.embed(clips)
        except ValueError as e:                     # an unreadable or wrongly-shaped clip
            return JSONResponse({"error": str(e)}, 422)
        # COUNTS AND TIMES ONLY — never a clip, never a vector. Audio seconds from the WAV size
        # (16 kHz mono 16-bit = 32 kB/s, less the 44-byte header) so this costs no decode.
        audio_s = sum(max(0, len(c) - 44) for c in clips) / 32000
        print(f"{SERVICE}: embedded {len(clips)} clip(s), {audio_s:.0f}s of audio, in "
              f"{time.monotonic() - started:.1f}s", flush=True)
        return JSONResponse({"model": embedder.model, "vectors": [list(v) for v in vectors]})

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"model": embedder.model})

    app = Starlette(routes=[Route("/embed", embed, methods=["POST"]),
                            Route("/healthz", healthz, methods=["GET"])])
    app.add_middleware(BearerAuthMiddleware, public_paths=("/healthz",))
    return app


def main() -> None:
    netbind.refuse_open(SERVICE)
    embedder = EcapaEmbedder()
    import os
    print(f"{SERVICE}: serving {embedder.model} on http://{config.BIND_HOST}:{config.VOICEPRINT_PORT} "
          f"with {embedder.threads} thread(s) (host reports {os.cpu_count()} cores)  {config.build_id()}",
          flush=True)
    port = config.VOICEPRINT_PORT
    netbind.run(app_for(embedder), port,
                sockets=netbind.dual_stack_sockets(port) if config.BIND_HOST == "::" else None)


if __name__ == "__main__":
    main()
