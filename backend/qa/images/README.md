# QA Runner Image

Build the polyglot QA sandbox image used by `DockerQARunner`:

```bash
docker build -t devflow/qa-runner:latest backend/qa/images
```

The image bundles:
- Node 22 + npm + pnpm + yarn (from the Playwright base)
- Playwright 1.49 + Chromium/Firefox/WebKit pre-installed
- Python 3 + pip + uv
- curl, jq, git, build-essential

Override the image tag at runtime with the `QA_DOCKER_IMAGE` env var.
