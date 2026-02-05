# LLM Gateway - Detailed Execution Guide

This guide walks you through setting up the entire LLM inference pipeline step by step.

---

## 📋 Overview

You're setting up a three-component system:

| Component | Location | Purpose |
|-----------|----------|---------|
| **FastAPI Gateway** | Oracle Cloud VM | Permanent API endpoint, request routing |
| **GPU Worker** | Google Colab | LLM inference using T4 GPU |
| **Cloudflare Tunnel** | Both | Secure, no-public-IP networking |

---

## 🔧 Part 1: Cloudflare Setup (15 minutes)

### 1.1 Create Cloudflare Account & Add Domain

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Sign up or log in
3. Add your domain and update nameservers at your registrar
4. Wait for DNS activation (usually < 1 hour)

### 1.2 Create Zero Trust Tunnels

Go to **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**

#### Tunnel 1: Gateway (Permanent - for Oracle VM)

1. Name: `llm-gateway`
2. Choose **Cloudflared** connector
3. Copy the tunnel token (save it securely!)
4. Add public hostname:
   - Subdomain: `api` (or your choice)
   - Domain: `your-domain.com`
   - Service: `http://localhost:8080`
5. Save

#### Tunnel 2: Worker (Temporary - for Colab)

1. Name: `llm-worker`
2. Choose **Cloudflared** connector
3. Copy the tunnel token (save it securely!)
4. Add public hostname:
   - Subdomain: `worker` (or your choice)
   - Domain: `your-domain.com`
   - Service: `http://localhost:8000`
5. Save

**Result:** You now have two URLs ready:
- `https://api.your-domain.com` → Your gateway
- `https://worker.your-domain.com` → Your Colab worker

---

## 🖥️ Part 2: AWS EC2 Setup (30 minutes)

### 2.1 Create EC2 Instance

1. Go to [AWS Console](https://console.aws.amazon.com/ec2/)
2. Click **Launch Instance**
3. Configuration:
   - Name: `llm-gateway`
   - AMI: **Ubuntu Server 22.04 LTS** (64-bit x86)
   - Instance type: **t3.micro** (Free Tier eligible)
   - Key pair: Create new or select existing
   - Network settings:
     - Allow SSH traffic from your IP
     - *(No HTTP/HTTPS rules needed - Cloudflare tunnel uses outbound only)*
   - Storage: 8 GB gp3 (default is fine)
4. Launch instance and wait for it to start

### 2.2 Security Group (Firewall)

The default security group with SSH access is sufficient. **No inbound HTTP rules needed** because Cloudflare tunnel makes outbound connections only.

If you want to test locally before tunnel setup, temporarily add:
- Type: Custom TCP, Port: 8080, Source: Your IP

### 2.3 Connect and Setup

```bash
# SSH into your EC2 instance (use the public IP from AWS console)
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Log out and back in for docker group
exit
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Verify
docker --version
docker compose version
```

### 2.4 Deploy Gateway

```bash
# Create directory
mkdir -p ~/llm-gateway
cd ~/llm-gateway

# Create files (copy from your local LLM folder)
# Option 1: Clone your repo
git clone https://your-repo-url .

# Option 2: SCP from your machine
# scp -r -i your-key.pem /path/to/LLM/* ubuntu@<VM-IP>:~/llm-gateway/

# Create .env file
cat > .env << 'EOF'
LLM_DEBUG=false
LLM_PORT=8080
LLM_WORKER_REQUEST_TIMEOUT=120
EOF

# Create tunnel token file
echo "CLOUDFLARE_TUNNEL_TOKEN=<your-gateway-tunnel-token>" > .env.docker

# Build and start
docker compose --env-file .env.docker up -d --build

# Check status
docker compose logs -f
```

### 2.5 Verify Gateway

```bash
# From VM
curl http://localhost:8080/health

# From anywhere (after tunnel connects)
curl https://api.your-domain.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "worker_status": "offline",
  "worker_url": null
}
```

---

## 📁 Part 3: Google Drive Setup (10 minutes)

### 3.1 Prepare Model Storage

1. Go to [Google Drive](https://drive.google.com/)
2. Create folder structure:
   ```
   MyDrive/
   └── llm/
       └── models/
           └── (your GGUF model here)
   ```

### 3.2 Upload Model

Download a GGUF model (recommendations for T4 with 15GB VRAM):

| Model | Size | Notes |
|-------|------|-------|
| CodeLlama-7B-Q4_K_M | ~4 GB | Good for code tasks |
| Mistral-7B-Q4_K_M | ~4 GB | General purpose |
| DeepSeek-Coder-6.7B-Q4 | ~4 GB | Code generation |
| Llama-2-13B-Q4_K_M | ~8 GB | Better quality, slower |

Upload your chosen model to `MyDrive/llm/models/`

### 3.3 Note the Path

Your model path will be:
```
/content/drive/MyDrive/llm/models/your-model-name.gguf
```

---

## 🚀 Part 4: Colab Worker Setup (15 minutes)

### 4.1 Upload Notebook

1. Go to [Google Colab](https://colab.research.google.com/)
2. File → Upload notebook → Select `colab_worker.ipynb`

### 4.2 Enable GPU

1. Runtime → Change runtime type
2. Hardware accelerator: **T4 GPU**
3. Save

### 4.3 Configure Notebook

Edit the **Configuration** cell with your values:

```python
# Path to your GGUF model in Google Drive
MODEL_PATH = "/content/drive/MyDrive/llm/models/codellama-7b-q4_k_m.gguf"

# Path to llama.cpp folder (will be created if missing)
LLAMA_CPP_PATH = "/content/drive/MyDrive/llm/llama.cpp"

# Your WORKER tunnel token (not the gateway one!)
CLOUDFLARE_TUNNEL_TOKEN = "eyJhIjoiYWJjMTIz..."

# Your gateway URL
GATEWAY_URL = "https://api.your-domain.com"
```

In the **Register with Gateway** cell:
```python
# Your worker tunnel public URL
WORKER_PUBLIC_URL = "https://worker.your-domain.com"
```

### 4.4 Run All Cells

1. Click **Runtime** → **Run all**
2. Watch for progress:
   - Mount Drive: ~5 seconds
   - Compile llama.cpp (first time only): ~5 minutes
   - Load model: 30-60 seconds
   - Start tunnel: ~10 seconds
   - Register with gateway: ~2 seconds

### 4.5 Verify

Look for:
```
════════════════════════════════════════════════════════════
🎉 READY - Worker is now serving requests!
════════════════════════════════════════════════════════════
```

---

## ✅ Part 5: Testing (5 minutes)

### 5.1 Check Full Pipeline

```bash
# From anywhere with internet
curl https://api.your-domain.com/health
```

Should show:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "worker_status": "online",
  "worker_url": "https://worker.your-domain.com"
}
```

### 5.2 Test Generation

```bash
curl -X POST https://api.your-domain.com/generate-tests \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b",
    "language": "python",
    "test_framework": "pytest"
  }'
```

### 5.3 Test Direct Completion

```bash
curl -X POST https://api.your-domain.com/completion \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a Python function to calculate fibonacci:",
    "max_tokens": 200,
    "temperature": 0.7
  }'
```

---

## 🔄 Day-to-Day Usage

### Starting the Worker

1. Open Colab notebook
2. Runtime → Run all
3. Wait for "READY"

### Stopping the Worker

1. Run the **Cleanup** cell in Colab
2. Or just close the browser tab (worker will unregister on next health check)

### Monitoring

```bash
# Check worker status
curl https://api.your-domain.com/worker-status

# View gateway logs (on VM)
docker compose logs -f llm-gateway
```

---

## 🛠️ Troubleshooting

### "No worker registered"

**Cause:** Colab notebook not running or tunnel failed

**Fix:**
1. Open Colab notebook
2. Run all cells
3. Check for errors in tunnel cell
4. Verify tunnel token is correct

### "Worker unreachable"

**Cause:** Cloudflare tunnel not connected

**Fix:**
1. Check Cloudflare Zero Trust → Tunnels → Status
2. Verify token matches the worker tunnel
3. Re-run tunnel cell in Colab

### "Request timeout"

**Cause:** Model still loading or large generation

**Fix:**
1. Wait for model to fully load (check Colab output)
2. Reduce `max_tokens` in request
3. Increase `LLM_WORKER_REQUEST_TIMEOUT` on VM

### Colab disconnects after idle

**Cause:** Colab free tier has ~90 minute idle timeout

**Fix:**
1. Re-run notebook when needed
2. Consider Colab Pro for longer sessions
3. Add a keep-alive mechanism (periodic requests)

### Slow first request

**Cause:** Model needs to load into GPU memory

**Fix:**
- This is normal (30-60 seconds for 7B model)
- Subsequent requests are ~1-5 seconds

---

## 📊 Cost Analysis

| Component | Cost | Limit |
|-----------|------|-------|
| AWS t3.micro | Free (12 months) | 750 hours/month, 1GB RAM |
| Cloudflare Tunnel | Free | Unlimited |
| Colab GPU | Free | ~12 hours/day, resets daily |
| Google Drive | Free | 15 GB |

**Total: $0/month** for first 12 months (AWS Free Tier), then ~$8/month for t3.micro

---

## 🎯 Next Steps

1. **Add API Key** for security: Set `LLM_API_KEY` in `.env`
2. **Monitor usage** with Cloudflare Analytics
3. **Add more models** by copying the worker tunnel setup
4. **Scale up** by using Colab Pro or GCP for longer sessions
