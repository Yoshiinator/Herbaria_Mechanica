# SAM3 FastAPI Docker — Run Instructions

This package contains **Meta's Segment Anything Model 3 (SAM3)** as a FastAPI service in Docker, with the same model and setup as the original project.

## Requirements

- **Docker** and **Docker Compose**
- **NVIDIA GPU** with drivers and **NVIDIA Container Toolkit** (for GPU support)
- Optional: **HuggingFace token** if the model is not pre-included (see [Model](#model) below)

## Quick Start

### 1. Extract the ZIP

Extract `sam3-fastapi-docker.zip` to a folder, e.g. `sam3-fastapi-docker`.

### 2. (Optional) HuggingFace token

If the model is not already in `models/`, you need a HuggingFace token with access to [facebook/sam3](https://huggingface.co/facebook/sam3):

1. Create an account: https://huggingface.co/join  
2. Request model access: https://huggingface.co/facebook/sam3  
3. Create a token: https://huggingface.co/settings/tokens  

Copy `.env.example` to `.env` and set your token:

```bash
# Windows (PowerShell)
Copy-Item .env.example .env
# Then edit .env and set: HF_TOKEN=your_token_here

# Linux/macOS
cp .env.example .env
# Then edit .env and set: HF_TOKEN=your_token_here
```

### 3. Run the container

**Using Docker Compose (recommended):**

```bash
# Build and start (first time may take several minutes)
docker compose up -d --build

# Or: build first, then start
docker compose build
docker compose up -d
```

**Using the provided scripts:**

```powershell
# Windows PowerShell
.\run.ps1
```

```bash
# Linux/macOS
chmod +x run.sh && ./run.sh
```

### 4. Check that it’s running

- **API:** http://localhost:8222  
- **Health:** http://localhost:8222/health  
- **GUI:** http://localhost:8222/gui  
- **Docs:** http://localhost:8222/docs  

---

## Docker Compose commands

| Command | Description |
|--------|-------------|
| `docker compose up -d --build` | Build image and start container in background |
| `docker compose up -d` | Start existing image (no rebuild) |
| `docker compose down` | Stop and remove container |
| `docker compose logs -f` | Follow container logs |
| `docker compose ps` | List running services |

---

## Model

- The app looks for the SAM3 checkpoint under `./models` (mounted as `/models` in the container).
- **If you have the model already:** Copy your full `models` folder (including `models/huggingface/hub/models--facebook--sam3/...`) into this project’s `models/` so the layout is:

  ```
  models/
  └── huggingface/
      └── hub/
          └── models--facebook--sam3/
              ├── blobs/
              ├── refs/
              └── snapshots/
  ```

- **If this package has `blobs/` and `refs/main` but no `snapshots/` folder:** The app looks for `snapshots/<commit>/sam3.pt`. Create it once (PowerShell, run from project root):

  ```powershell
  $commit = Get-Content "models\huggingface\hub\models--facebook--sam3\refs\main" -Raw
  $blob = Get-ChildItem "models\huggingface\hub\models--facebook--sam3\blobs" | Select-Object -First 1
  New-Item -ItemType Directory "models\huggingface\hub\models--facebook--sam3\snapshots\$($commit.Trim())" -Force
  Copy-Item $blob.FullName "models\huggingface\hub\models--facebook--sam3\snapshots\$($commit.Trim())\sam3.pt" -Force
  ```

- **If the ZIP did not include the model:** Set `HF_TOKEN` in `.env` (see step 2). On first request (e.g. open `/gui` or call `/api/segment`), the service will download the model into `./models`.

---

## Example API usage

### Health check

```bash
curl http://localhost:8222/health
```

### Segment by file path (recommended)

Send an image path and a text prompt (path must be inside the container; use mounted volumes like `/data` or `/outputs`):

```bash
curl -X POST "http://localhost:8222/api/segment" \
  -F "file_path=/data/your_image.jpg" \
  -F "text_prompt=plant"
```

### Segment by base64 (JSON)

```bash
# PowerShell: encode image to base64 and call API
$base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\to\image.jpg"))
$body = @{ image_base64 = $base64; text_prompt = "plant" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8222/api/segment/json" -Method Post -Body $body -ContentType "application/json"
```

```bash
# Linux/macOS (with jq)
BASE64=$(base64 -w0 your_image.jpg)
curl -X POST "http://localhost:8222/api/segment/json" \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$BASE64\", \"text_prompt\": \"plant\"}"
```

---

## Port and volumes

- **Host port:** `8222` → container port `8000`. Change in `docker-compose.yml` if needed:

  ```yaml
  ports:
    - "8222:8000"   # change 8222 to your port
  ```

- **Mounted folders:**

  | Host folder | Container path | Purpose |
  |-------------|----------------|---------|
  | `./models`  | `/models`      | HuggingFace model cache |
  | `./outputs` | `/outputs`     | Result images and metadata |
  | `./data`    | `/data`        | Input images (read-only) |

  Put images in `./data` and use `file_path=/data/filename.jpg` in `/api/segment`.

---

## Optional: n8n shared folder

To share a folder with n8n, add a volume in `docker-compose.yml`:

```yaml
volumes:
  - ./models:/models
  - ./outputs:/outputs
  - ./app/static:/app/app/static:ro
  - ./data:/data:ro
  # Optional: path to your n8n files (adjust to your path)
  # - /path/to/n8n-files:/home/node/.n8n-files:rw
```

Then you can use paths like `/home/node/.n8n-files/input/image.jpg` in the API.

---

## Troubleshooting

- **CUDA errors:** Ensure NVIDIA drivers and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) are installed; run `nvidia-smi` on the host.
- **Model not loading:** Check `./models` layout or set `HF_TOKEN` in `.env` and trigger a request to download the model.
- **Port in use:** Change `8222` in `docker-compose.yml` under `ports`.
- **Logs:** `docker compose logs -f sam3-gpu` (or the service name from `docker compose ps`).

---

## Summary

1. Extract the ZIP.  
2. Optionally set `HF_TOKEN` in `.env` if the model is not in `models/`.  
3. Run: `docker compose up -d --build`.  
4. Use API at http://localhost:8222 or open http://localhost:8222/gui.
