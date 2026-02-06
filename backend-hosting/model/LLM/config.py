"""
LLM Configuration Settings
==========================
Central configuration for the local LLM module.
"""

import os
from pathlib import Path

# Base paths
LLM_DIR = Path(__file__).parent
MODELS_DIR = LLM_DIR / "models"
CODELLAMA_DIR = MODELS_DIR / "codellama"

# Model settings
MODEL_CONFIG = {
    "name": "CodeLlama-7B-Instruct-GGUF",
    "filename": "codellama-7b-instruct.Q4_K_M.gguf",
    "repo_id": "TheBloke/CodeLlama-7B-Instruct-GGUF",
    "file_pattern": "codellama-7b-instruct.Q4_K_M.gguf",
    "model_path": CODELLAMA_DIR / "codellama-7b-instruct.Q4_K_M.gguf",
    "context_length": 4096,
    "max_tokens": 2048,
    "temperature": 0.1,  # Low for deterministic test generation
    "top_p": 0.95,
    "repeat_penalty": 1.1,
}

# GPU Configuration (for ctransformers)
GPU_CONFIG = {
    "n_gpu_layers": 45,  # 45 layers for RTX 4050 (6GB VRAM)
    "n_batch": 512,
    "n_threads": None,  # None = auto-detect
    "use_mmap": True,
    "use_mlock": False,
    "verbose": False,
}

# Fallback to CPU if GPU fails
CPU_FALLBACK = {
    "n_gpu_layers": 0,
    "n_batch": 256,
    "n_threads": os.cpu_count() or 4,
    "use_mmap": True,
    "use_mlock": False,
    "verbose": False,
}

# Generation settings for test generation
GENERATION_CONFIG = {
    "max_tokens": 2048,
    "temperature": 0.1,
    "top_p": 0.95,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "stop": ["```\n\n", "</tests>", "---", "\n\n\n"],
}

# Prompt templates (Llama Instruct format)
SYSTEM_PROMPT = """You are an expert software testing engineer. Generate test cases in valid JSON format only."""

TEST_GENERATION_PROMPT_TEMPLATE = """[INST] You are a test case generator. Output ONLY valid JSON, no explanations.

Generate API test cases for this code:
{code_description}

Language: {language}

Output format (generate 3-6 tests):
{{"tests":[{{"name":"test_example","endpoint":"/api/example","method":"POST","payload":{{"key":"value"}},"expected_status":200,"description":"What this tests"}}]}}

Generate tests for: valid inputs, invalid inputs, edge cases, security.

Your JSON output: [/INST]"""
