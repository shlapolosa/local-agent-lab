# One image, seven roles — the lab's Python services share one package (src/lab: core,
# platform, substrate, workloads). Select the role with the container command (each role gets only its own env —
# deploy/railway.py ROLE_ENV):
#   gateway     litellm --config config/litellm-config.yaml --port 4000
#   adoit-mcp   python -m lab.substrate.mcp.adoit.server
#   semantic-mcp python -m lab.substrate.mcp.semantic.server
#   storage-mcp python -m lab.substrate.mcp.storage.server      (read-only governed object store, :9300)
#   review      streamlit run src/lab/substrate/review/app.py --server.port 8501 --server.headless true
#   telegram    python -m lab.substrate.channels.telegram
#   wf-visio    python -m lab.workloads.visio_to_archimate.consumer   (long-lived workload host)
#
# BUILD SPEED (measured Sep 4 2026 — see docs/reviews/ and deploy/README.md):
#  * `python:3.12-slim` (46 MB compressed) not the full image (411 MB): ~20 s of every build was image
#    export/push. The full image was originally chosen because prisma downloads its own Node whose
#    binary needs libatomic1 etc.; installing Debian's `nodejs` (20.x, above prisma's 16.13 minimum)
#    instead makes prisma use the GLOBAL node — no download, no missing shared libraries.
#  * `uv` replaces pip for the dependency layer (same wheels, ~5-10x faster resolve+install).
#  * BuildKit cache mounts keep the uv/apt caches warm between builds. NOTE: on a Railway REPO build
#    the id must be `s/<serviceId>-<name>` (no env vars); the primary path is now a single CI build
#    (.github/workflows/image.yml -> GHCR) that all services pull, so plain ids are used here.
#  * `prisma generate` sits ABOVE the source COPY: it depends only on litellm_proxy_extras (a
#    dependency), so a source-only change no longer re-runs it (~15 s per service per deploy).
#  * COPY order is least-changing first, so a src/ edit invalidates only the last two layers.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=0 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# git+zip: scripts/register_skill.sh zips a skill and derives the source from `git remote`.
# openssl/ca-certificates: prisma query engine + every outbound HTTPS call.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        git zip openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# node + npm for prisma's CLI (gateway role). prisma-python resolves BOTH globally (shutil.which) and,
# if EITHER is missing, downloads its own nodeenv — whose npm then fails with exit 127 (verified
# locally, Sep 4 2026). Taken from the official image rather than apt: Debian ships npm as ~250
# separate node-* packages, which costs more than the slim base saves. Same Debian ABI, so the
# binaries just work.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && node --version && npm --version

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r deploy/requirements.txt

# prisma client for the gateway role (schema ships with litellm_proxy_extras — a dependency, so this
# layer is cached until requirements change). No `|| true`: a failure here means a broken gateway,
# so fail the build loudly instead of shipping it silently.
RUN python -c "import litellm_proxy_extras, os; print(os.path.dirname(litellm_proxy_extras.__file__))" > /tmp/lpe \
 && prisma generate --schema "$(cat /tmp/lpe)/schema.prisma"

# --- application layers, least-changing first ---
COPY skills/ /app/skills/
COPY config/ /app/config/
COPY scripts/ /app/scripts/
COPY deploy/ /app/deploy/
COPY pyproject.toml /app/
COPY src/ /app/src/
RUN uv pip install --system --no-deps -e .   # `lab` importable everywhere; REPO_ROOT=/app, runtime state in /app/var

EXPOSE 4000 9100 9200 9300 8501
CMD ["python", "-m", "lab.substrate.mcp.adoit.server"]
