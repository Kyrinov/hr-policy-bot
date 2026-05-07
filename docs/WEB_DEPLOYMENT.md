# Web Deployment

This branch is intended for Render hosting with inference served from the local AGX through two ngrok HTTPS endpoints.

## Runtime Shape

- Render serves the FastAPI/static web app from the `web-app` branch.
- Render stores SQLite state under `APP_DATA_DIR`, mounted to `/var/data` by `render.yaml`.
- The AGX runs two local Ollama servers:
  - `gemma4:31b` on `127.0.0.1:11436` for orchestration and synthesis.
  - `gemma4:e4b` on `127.0.0.1:11435` for all eight specialist agents running in parallel.
- ngrok exposes each local Ollama server with a stable HTTPS endpoint.

## Render Environment

Set these in Render. `render.yaml` marks the ngrok values as manually supplied secrets.

```text
APP_DATA_DIR=/var/data
OLLAMA_ORCHESTRATOR_MODEL=gemma4:31b
OLLAMA_SPECIALIST_MODEL=gemma4:e4b
OLLAMA_ORCHESTRATOR_HOST=https://<your-31b-domain>.ngrok.app
OLLAMA_SPECIALIST_HOST=https://<your-e4b-domain>.ngrok.app
```

If the ngrok endpoints use Basic Auth, set this too:

```text
OLLAMA_AUTH_HEADER=Basic <base64(username:password)>
```

Use role-specific values only if the two endpoints use different credentials:

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

## ngrok Setup

Install ngrok on the AGX, then authenticate the agent:

```bash
ngrok config add-authtoken <your-ngrok-authtoken>
```

Create two stable ngrok domains in the ngrok dashboard, one for each Ollama server. Then add endpoints to the ngrok config.

Example ngrok v3 config:

```yaml
version: 3

agent:
  authtoken: <your-ngrok-authtoken>

endpoints:
  - name: ollama-orchestrator
    url: https://<your-31b-domain>.ngrok.app
    upstream:
      url: http://127.0.0.1:11436

  - name: ollama-specialists
    url: https://<your-e4b-domain>.ngrok.app
    upstream:
      url: http://127.0.0.1:11435
```

Start both endpoints:

```bash
ngrok start ollama-orchestrator ollama-specialists
```

Or:

```bash
ngrok start --all
```

Verify from any machine that can reach the public internet:

```bash
curl https://<your-31b-domain>.ngrok.app/api/tags
curl https://<your-e4b-domain>.ngrok.app/api/tags
```

## Optional Basic Auth

Because ngrok endpoints are public unless protected, Basic Auth is recommended for the Ollama endpoints.

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

Attach that policy to both ngrok endpoints. Then base64 encode the credential and set Render's `OLLAMA_AUTH_HEADER`:

```bash
printf 'render:<long-random-password>' | base64 -w 0
```

```text
OLLAMA_AUTH_HEADER=Basic <encoded-value>
```

Verify:

```bash
curl -H 'Authorization: Basic <encoded-value>' https://<your-31b-domain>.ngrok.app/api/tags
curl -H 'Authorization: Basic <encoded-value>' https://<your-e4b-domain>.ngrok.app/api/tags
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
