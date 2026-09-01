# One image, four roles — the lab's Python services share code (skill engine, semantic layer,
# shared/). Select the role with the container command:
#   gateway     litellm --config gateway/litellm-config.yaml --port 4000
#   adoit-mcp   python mcp/adoit_mcp/server.py
#   semantic-mcp python mcp/semantic_mcp/server.py
#   review      streamlit run review/app.py --server.port 8501 --server.headless true
#   telegram    python channels/telegram.py
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0
WORKDIR /app
# prisma generate downloads a prebuilt Node.js to run its CLI; that Node needs libatomic.so.1
# (libatomic1), and the engine download needs ca-certificates — neither is in python:3.12-slim.
RUN apt-get update && apt-get install -y --no-install-recommends git zip ca-certificates openssl libatomic1 \
 && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt
COPY . /app
# prisma client for the gateway role (schema ships with litellm_proxy_extras). No `|| true`: a
# failure here means a broken gateway, so fail the build loudly instead of shipping it silently.
RUN python -c "import litellm_proxy_extras, os; print(os.path.dirname(litellm_proxy_extras.__file__))" > /tmp/lpe \
 && prisma generate --schema "$(cat /tmp/lpe)/schema.prisma"
EXPOSE 4000 9100 9200 8501
CMD ["python", "mcp/adoit_mcp/server.py"]
