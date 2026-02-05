# ETTA-X: AI-Powered Test Automation & Impact Analysis Platform

<p align="center">
  <img src="frontend/static/assets/etta_x_logo.png" alt="ETTA-X Logo" width="120"/>
</p>

<p align="center">
  <strong>Intelligent Test Generation | Risk-Based Prioritization | Self-Healing Tests</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#api-reference">API Reference</a> •
  <a href="#credits">Credits</a>
</p>

---

## 📋 Overview

**ETTA-X** (Enterprise Test & Transformation Accelerator - eXtended) is an AI-powered platform that automatically generates, prioritizes, and manages test cases based on code changes. It uses machine learning for impact analysis and local LLM models for intelligent test generation.

> ⚠️ **Infrastructure Note**: Due to infrastructure limitations, the demo executable uses **Google Gemini API** for test generation. The actual local prototype uses **CodeLlama 7B** running via Ollama for completely offline, privacy-preserving test generation.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **🔍 Impact Analysis** | Automatically analyzes code changes and calculates risk scores |
| **🤖 AI Test Generation** | Generates test cases using CodeLlama (local) or Gemini (demo) |
| **📊 Risk-Based Prioritization** | ML model prioritizes tests based on change risk and code criticality |
| **🔗 GitHub Integration** | Webhook-based pipeline triggers on every push |
| **📈 Dashboard Analytics** | Real-time metrics on repositories, analyses, and test coverage |
| **🌙 Dark/Light Theme** | Full theme support for comfortable viewing |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **Git**
- **Ollama** (for local LLM - optional for demo)
- **ngrok** (for GitHub webhook tunneling)

### Step-by-Step Setup

#### Step 1: Clone the Repository

```bash
git clone https://github.com/EttaX-Developers/ETTA-X.git
cd ETTA-X
```

#### Step 2: Install Python Dependencies

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\Activate.ps1

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r LLM/requirements.txt
```

#### Step 3: Install Ollama & CodeLlama (Local LLM)

```bash
# Download Ollama from https://ollama.ai
# Then pull CodeLlama model:
ollama pull codellama:7b-instruct

# Start Ollama server
ollama serve
```

#### Step 4: Start the Backend Server

```bash
# From project root
python -m uvicorn backend.app.app:app --host 0.0.0.0 --port 8000 --reload
```

#### Step 5: Setup ngrok for GitHub Webhooks

```bash
# Start ngrok tunnel
ngrok http 8000

# Copy the HTTPS URL (e.g., https://xxxx.ngrok.io)
```

#### Step 6: Configure GitHub Webhook

1. Go to your GitHub repository → **Settings** → **Webhooks**
2. Click **Add webhook**
3. Set **Payload URL**: `https://your-ngrok-url.ngrok.io/api/github/webhook`
4. Set **Content type**: `application/json`
5. Select **Just the push event**
6. Click **Add webhook**

#### Step 7: Launch the Desktop App

**Option A: Using the batch file**
```bash
# Double-click ETTAX_Beta.bat
# OR run:
.\ETTAX_Beta.bat
```

**Option B: Manual launch**
```bash
cd electron
npm install
npm run setup
```

#### Step 8: Login with GitHub

1. Click "Sign in with GitHub" in the app
2. Authorize the ETTA-X application
3. Your repositories will automatically appear

---

## 📖 Using the Features

### 1. Dashboard

The main dashboard displays:
- Total repositories connected
- Number of analyses performed
- High-risk changes detected
- Tests suggested by the AI

### 2. Repositories

- View all connected GitHub repositories
- See last commit and analysis status
- Click to view detailed repository info

### 3. Impact Analysis

1. Navigate to **Impact Analysis** from the sidebar
2. View all webhook events from your repositories
3. Each event shows:
   - **Risk Score** (0-100): Higher = more critical
   - **Files Changed**: Number of modified files
   - **Change Types**: Type of modifications detected
4. Click on an event to see detailed analysis

### 4. Test Runs

1. Navigate to **Test Runs** from the sidebar
2. View all AI-generated tests
3. Filter by:
   - **Priority**: High, Medium, Low
   - **Status**: Pending, Passed, Failed
4. Click a test to see:
   - Test name and description
   - HTTP method and endpoint
   - Expected status code
   - Priority score and category

### 5. Triggering the Pipeline

Simply push code to your connected repository:

```bash
git add .
git commit -m "Your changes"
git push origin main
```

The pipeline automatically:
1. ✅ Receives webhook from GitHub
2. ✅ Analyzes code diff
3. ✅ Calculates impact/risk score
4. ✅ Generates tests via AI (if risk > threshold)
5. ✅ Prioritizes tests using ML model
6. ✅ Updates the UI in real-time

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ETTA-X Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐     ┌──────────┐     ┌──────────────────────┐    │
│  │  GitHub  │────▶│  Webhook │────▶│   Backend (FastAPI)  │    │
│  │   Push   │     │ Receiver │     │                      │    │
│  └──────────┘     └──────────┘     │  ┌────────────────┐  │    │
│                                     │  │ Diff Analyzer  │  │    │
│                                     │  └───────┬────────┘  │    │
│                                     │          │           │    │
│  ┌──────────┐                      │  ┌───────▼────────┐  │    │
│  │ Electron │◀────────────────────▶│  │Impact Analyzer │  │    │
│  │   App    │     REST API         │  └───────┬────────┘  │    │
│  └──────────┘                      │          │           │    │
│                                     │  ┌───────▼────────┐  │    │
│                                     │  │  LLM (Ollama)  │  │    │
│                                     │  │   CodeLlama    │  │    │
│                                     │  └───────┬────────┘  │    │
│                                     │          │           │    │
│                                     │  ┌───────▼────────┐  │    │
│                                     │  │ ML Prioritizer │  │    │
│                                     │  └────────────────┘  │    │
│                                     └──────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 API Reference

### Webhook Endpoint
```
POST /api/github/webhook
```
Receives GitHub push events and triggers the analysis pipeline.

### Impact Analysis
```
GET /api/analysis/events
```
Returns all analyzed webhook events with risk scores.

### Generated Tests
```
GET /api/tests/generated
```
Returns all AI-generated tests from the pipeline.

### Test Pipeline Status
```
GET /api/tests/status
```
Returns LLM status and pipeline health.

---

## 📦 Project Structure

```
ETTA-X/
├── backend/
│   ├── api/
│   │   ├── diff_analyzer.py      # Git diff analysis
│   │   ├── git_repo.py           # Repository management
│   │   └── test_pipeline.py      # Test generation pipeline
│   ├── app/
│   │   ├── app.py                # FastAPI application
│   │   └── database.py           # SQLite database
│   ├── data/
│   │   └── etta_x.db             # Application database
│   └── model/
│       └── LLM/                  # LLM integration
├── electron/
│   ├── main.js                   # Electron main process
│   └── preload.js                # Preload scripts
├── frontend/
│   ├── pages/                    # HTML pages
│   └── static/                   # CSS, JS, assets
├── LLM/
│   └── llm_model.py              # Ollama/LLM wrapper
├── Z_Data_set/
│   ├── train_model.py            # ML model training
│   └── etta_x_dataset.csv        # Training dataset
├── process_pending.py            # Pipeline processor
├── requirements.txt              # Python dependencies
├── ETTAX_Beta.bat               # Quick start script
└── README.md                     # This file
```

---

## 🙏 Credits & Acknowledgments

### External APIs

| API | Usage | Link |
|-----|-------|------|
| **Ollama** | Local LLM inference server | [ollama.ai](https://ollama.ai) |
| **Google Gemini** | Demo LLM (API fallback) | [ai.google.dev](https://ai.google.dev) |
| **GitHub API** | OAuth & webhook integration | [docs.github.com](https://docs.github.com) |

### Machine Learning Models

| Model | Purpose | Source |
|-------|---------|--------|
| **CodeLlama 7B Instruct** | Test case generation | [Meta AI](https://ai.meta.com/llama/) |
| **XGBoost** | Test prioritization | [xgboost.readthedocs.io](https://xgboost.readthedocs.io) |
| **Scikit-learn** | Feature engineering | [scikit-learn.org](https://scikit-learn.org) |

### Libraries & Frameworks

| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.100+ | Backend REST API |
| Electron | 28+ | Desktop application |
| SQLAlchemy | 2.0+ | Database ORM |
| GitPython | 3.1+ | Git operations |
| httpx | 0.25+ | Async HTTP client |
| Pandas | 2.0+ | Data processing |
| NumPy | 1.24+ | Numerical computing |

### Datasets

- Custom synthetic dataset generated for test prioritization training
- Located in `Z_Data_set/etta_x_enhanced.csv`

---

## ⚙️ Configuration

### Environment Variables (Optional)

```bash
# For demo mode with Gemini
GEMINI_API_KEY=your_api_key_here

# GitHub OAuth (already configured)
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
```

### LLM Configuration

Edit `LLM/llm_model.py` to switch between:
- **Ollama (Local)**: Default, privacy-preserving
- **Gemini (Cloud)**: Fallback for demo

---

## 🔒 Privacy & Security

- **Local Processing**: CodeLlama runs entirely on your machine
- **No Code Upload**: Your code never leaves your infrastructure
- **Secure OAuth**: GitHub OAuth 2.0 for authentication
- **Encrypted Storage**: SQLite with local file permissions

---

## 🐛 Troubleshooting

### Ollama not responding
```bash
# Check if Ollama is running
ollama list

# Restart Ollama
ollama serve
```

### Webhook not triggering
1. Check ngrok is running and URL is correct
2. Verify webhook settings in GitHub
3. Check backend logs for errors

### Tests not generating
- Ensure Ollama has the `codellama:7b-instruct` model
- Check `process_pending.py` output for errors
- Verify webhook events are being received

---

## 📄 License

This project is developed for the ETTA-X Hackathon 2026.

---

## 👥 Team

**EttaX-Developers**

---

<p align="center">
  Made with ❤️ for intelligent test automation
</p>
