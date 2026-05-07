# Web Deployment

This branch is intended for Render hosting with inference served from the local AGX through one ngrok HTTPS endpoint.

## Runtime Shape

- Render serves the FastAPI/static web app from the `web-app` branch.
- Render stores SQLite state under `APP_DATA_DIR`, mounted to `/var/data` by `render.yaml`.
- The AGX runs two local Ollama servers:
  - `gemma4:31b` on `127.0.0.1:11436` for orchestration and synthesis.
  - `gemma4:e4b` on `127.0.0.1:11435` for all eight specialist agents running in parallel.
- A small AGX-side proxy exposes both local Ollama servers under one local HTTP port.
- ngrok exposes that proxy with one stable HTTPS endpoint.

## Render Environment

Set these in Render. `render.yaml` includes the ngrok host values for the single-domain proxy. The optional auth header remains a manually supplied secret.

```text
APP_DATA_DIR=/var/data
OLLAMA_ORCHESTRATOR_MODEL=gemma4:31b
OLLAMA_SPECIALIST_MODEL=gemma4:e4b
OLLAMA_ORCHESTRATOR_HOST=https://veto-faceless-grime.ngrok-free.dev/orchestrator
OLLAMA_SPECIALIST_HOST=https://veto-faceless-grime.ngrok-free.dev/specialist
```

If the ngrok endpoints use Basic Auth, set this too:

```text
OLLAMA_AUTH_HEADER=Basic <base64(username:password)>
```

Use role-specific values only if you later split the endpoints again and use different credentials:

```text
OLLAMA_ORCHESTRATOR_AUTH_HEADER=Basic <base64(username:password)>
OLLAMA_SPECIALIST_AUTH_HEADER=Basic <base64(username:password)>
```

## AGX Ollama Services

Run each Ollama server in its own shell, tmux pane, or systemd service.

```bash
OLLAMA_HOST=127.0.0.1:11436 ollama serve
```

```bash
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL=8 ollama serve
```

Verify both servers can see the expected models:

```bash
OLLAMA_HOST=127.0.0.1:11436 ollama list
OLLAMA_HOST=127.0.0.1:11435 ollama list
```

If needed, pull models through the correct server:

```bash
OLLAMA_HOST=127.0.0.1:11436 ollama pull gemma4:31b
OLLAMA_HOST=127.0.0.1:11435 ollama pull gemma4:e4b
```

## AGX Proxy

Start the local proxy after both Ollama servers are running:

```bash
uvicorn scripts.ollama_ngrok_proxy:app --host 127.0.0.1 --port 11500
```

The proxy routes:

```text
http://127.0.0.1:11500/orchestrator/* -> http://127.0.0.1:11436/*
http://127.0.0.1:11500/specialist/* -> http://127.0.0.1:11435/*
```

Verify locally on the AGX:

```bash
curl http://127.0.0.1:11500/health
curl http://127.0.0.1:11500/orchestrator/api/tags
curl http://127.0.0.1:11500/specialist/api/tags
```

If you want to use different local ports, set these before starting the proxy:

```bash
ORCHESTRATOR_OLLAMA_UPSTREAM=http://127.0.0.1:11436 \
SPECIALIST_OLLAMA_UPSTREAM=http://127.0.0.1:11435 \
uvicorn scripts.ollama_ngrok_proxy:app --host 127.0.0.1 --port 11500
```

## ngrok Setup

Install ngrok on the AGX, then authenticate the agent:

```bash
ngrok config add-authtoken <your-ngrok-authtoken>
```

Create one stable ngrok domain in the ngrok dashboard. This deployment uses:

```text
https://veto-faceless-grime.ngrok-free.dev
```

Then add a single endpoint to the ngrok config that forwards to the AGX proxy.

Example ngrok v3 config:

```yaml
version: 3

agent:
  authtoken: <your-ngrok-authtoken>

endpoints:
  - name: ollama-proxy
    url: https://veto-faceless-grime.ngrok-free.dev
    upstream:
      url: http://127.0.0.1:11500
```

Start the endpoint:

```bash
ngrok start ollama-proxy
```

Or:

```bash
ngrok start --all
```

Verify from any machine that can reach the public internet:

```bash
curl https://veto-faceless-grime.ngrok-free.dev/health
curl https://veto-faceless-grime.ngrok-free.dev/orchestrator/api/tags
curl https://veto-faceless-grime.ngrok-free.dev/specialist/api/tags
```

## Optional Basic Auth

Because ngrok endpoints are public unless protected, Basic Auth is recommended for the Ollama proxy endpoint.

Create a traffic policy:

```yaml
on_http_request:
  - actions:
      - type: basic-auth
        config:
          realm: ollama
          credentials:
            - render:<long-random-password>
          enforce: true
```

Attach that policy to the ngrok endpoint. Then base64 encode the credential and set Render's `OLLAMA_AUTH_HEADER`:

```bash
printf 'render:<long-random-password>' | base64 -w 0
```

```text
OLLAMA_AUTH_HEADER=Basic <encoded-value>
```

Verify:

```bash
curl -H 'Authorization: Basic <encoded-value>' https://veto-faceless-grime.ngrok-free.dev/health
curl -H 'Authorization: Basic <encoded-value>' https://veto-faceless-grime.ngrok-free.dev/orchestrator/api/tags
curl -H 'Authorization: Basic <encoded-value>' https://veto-faceless-grime.ngrok-free.dev/specialist/api/tags
```

## Render Deploy

Create a Render Blueprint from `render.yaml` or create a Python web service manually:

- Branch: `web-app`
- Build command: `pip install -r requirements.txt && python -m playwright install chromium`
- Start command: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Persistent disk mount path: `/var/data`

After deploy, check:

```text
https://<render-service>.onrender.com/health
https://<render-service>.onrender.com/api/health
```
