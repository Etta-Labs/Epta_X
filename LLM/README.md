# LLM Gateway - Colab GPU Worker + AWS EC2

A cost-effective LLM inference pipeline using Google Colab's free T4 GPU with an AWS EC2 VM as a stable gateway, exposed via Cloudflare Tunnel.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLOUDFLARE                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         Zero Trust Tunnels                           │    │
│  │   ┌──────────────────┐              ┌──────────────────────┐        │    │
│  │   │  Gateway Tunnel  │              │   Worker Tunnel      │        │    │
│  │   │  (Permanent)     │              │   (Temporary)        │        │    │
│  │   └────────┬─────────┘              └──────────┬───────────┘        │    │
│  └────────────┼────────────────────────────────────┼───────────────────┘    │
└───────────────┼────────────────────────────────────┼────────────────────────┘
                │                                    │
                ▼                                    ▼
┌───────────────────────────┐          ┌────────────────────────────────┐
│       AWS EC2 VM          │          │       Google Colab             │
│  ┌─────────────────────┐  │          │  ┌──────────────────────────┐  │
│  │   FastAPI Gateway   │  │◄─────────┼──│  llama-server + T4 GPU   │  │
│  │   (Port 8080)       │  │  HTTP    │  │  (Port 8000)             │  │
│  └─────────────────────┘  │  Proxy   │  └──────────────────────────┘  │
│  ┌─────────────────────┐  │          │  ┌──────────────────────────┐  │
│  │   cloudflared       │──┼──────────┼──│  cloudflared             │  │
│  │   (outbound)        │  │          │  │  (outbound)              │  │
│  └─────────────────────┘  │          │  └──────────────────────────┘  │
│                           │          │  ┌──────────────────────────┐  │
│                           │          │  │  Google Drive            │  │
│                           │          │  │  ├── llama.cpp           │  │
│                           │          │  │  └── models/*.gguf       │  │
│                           │          │  └──────────────────────────┘  │
└───────────────────────────┘          └────────────────────────────────┘
        Always Running                       Temporary (On-Demand)
```

## Request Flow

1. **Client** sends request to `https://api.your-domain.com/generate-tests`
2. **Cloudflare** routes to AWS EC2 via permanent tunnel
3. **FastAPI Gateway** checks if worker is registered and healthy
4. **Gateway** forwards request to Colab worker via its Cloudflare tunnel
5. **llama-server** generates response using T4 GPU
6. **Response** flows back through the same path

## Quick Start

### Prerequisites

- AWS account (Free Tier eligible)
- Cloudflare account with a domain
- Google account for Colab
- Docker installed on VM

### 1. Setup Cloudflare Tunnels

Create two tunnels in Cloudflare Zero Trust Dashboard:

**Gateway Tunnel (Permanent)**
- Name: `llm-gateway`
- Route: `api.your-domain.com` → `http://localhost:8080`

**Worker Tunnel (For Colab)**
- Name: `llm-worker`
- Route: `worker.your-domain.com` → `http://localhost:8000`

### 2. Deploy to AWS EC2

```bash
# SSH into your EC2 instance
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Clone the repo
git clone your-repo-url llm-gateway
cd llm-gateway/LLM

# Create .env file
cp .env.example .env
nano .env  # Add your settings

# Create environment file for tunnel token
echo "CLOUDFLARE_TUNNEL_TOKEN=your-gateway-tunnel-token" > .env.docker

# Start services
docker-compose --env-file .env.docker up -d

# Check logs
docker-compose logs -f
```

### 3. Prepare Google Drive

Upload to your Google Drive:
```
/MyDrive/llm/
├── llama.cpp/          # Will be created on first run
└── models/
    └── your-model.gguf  # Your GGUF model file
```

### 4. Run Colab Notebook

1. Open `colab_worker.ipynb` in Google Colab
2. Enable GPU: Runtime → Change runtime type → T4 GPU
3. Update configuration cell with:
   - `MODEL_PATH`: Path to your GGUF model
   - `CLOUDFLARE_TUNNEL_TOKEN`: Your worker tunnel token
   - `GATEWAY_URL`: Your gateway URL (e.g., `https://api.your-domain.com`)
   - `WORKER_PUBLIC_URL`: Your worker tunnel URL (e.g., `https://worker.your-domain.com`)
4. Run all cells
5. Wait for "READY" message

### 5. Test the API

```bash
# Check gateway health
curl https://api.your-domain.com/health

# Check worker status
curl https://api.your-domain.com/worker-status

# Generate tests
curl -X POST https://api.your-domain.com/generate-tests \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def add(a, b):\n    return a + b",
    "language": "python"
  }'
```

## API Endpoints

### Gateway Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Gateway health + worker status |
| `/worker-status` | GET | Detailed worker information |
| `/register-worker` | POST | Register Colab worker URL |
| `/unregister-worker` | POST | Remove worker registration |
| `/generate-tests` | POST | Generate tests for code |
| `/completion` | POST | Generic LLM completion |

### Generate Tests Request

```json
{
  "code": "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)",
  "language": "python",
  "test_framework": "pytest",
  "max_tokens": 2048,
  "temperature": 0.3
}
```

### Generate Tests Response

```json
{
  "success": true,
  "tests": [
    {
      "name": "test_factorial_zero",
      "description": "Test factorial of 0 returns 1",
      "code": "def test_factorial_zero():\n    assert factorial(0) == 1",
      "test_type": "unit"
    }
  ],
  "raw_response": "...",
  "tokens_used": 156
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_DEBUG` | false | Enable debug logging |
| `LLM_API_KEY` | (none) | API key for authentication |
| `LLM_PORT` | 8080 | Gateway port |
| `LLM_WORKER_REQUEST_TIMEOUT` | 120 | Timeout for LLM requests (seconds) |
| `LLM_INACTIVITY_TIMEOUT_MINUTES` | 15 | Inactivity warning threshold |

## Troubleshooting

### Worker not reachable
- Check Colab notebook is running
- Verify Cloudflare tunnel is connected
- Check worker URL is registered: `GET /worker-status`

### Slow responses
- First request loads model into GPU memory
- Subsequent requests are faster
- Consider reducing `CONTEXT_SIZE` if running out of memory

### Colab disconnects
- Colab has idle timeouts (usually 90 minutes)
- Keep the browser tab active or use Colab Pro
- Re-run the notebook when needed

## Files

```
LLM/
├── main.py              # FastAPI application
├── config.py            # Configuration management
├── colab_client.py      # HTTP client for Colab worker
├── models.py            # Pydantic request/response models
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container configuration
├── docker-compose.yml   # Docker orchestration
├── .env.example         # Environment template
├── colab_worker.ipynb   # Colab GPU worker notebook
└── README.md            # This file
```

## License

MIT
