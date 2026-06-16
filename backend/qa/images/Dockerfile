FROM mcr.microsoft.com/playwright:v1.49.0-noble

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV NPM_CONFIG_UPDATE_NOTIFIER=false

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      curl \
      jq \
      git \
      ca-certificates \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/local/bin/python \
    && python3 -m pip install --no-cache-dir --break-system-packages \
        pipx \
        uv

RUN npm install -g pnpm@9 yarn@1 || true

WORKDIR /workspace

CMD ["sleep", "infinity"]
