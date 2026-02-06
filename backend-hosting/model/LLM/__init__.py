"""
ETTA-X Local LLM Module
=======================
Local GGUF model inference for AI-powered test generation.

Uses CodeLlama-7B-Instruct quantized model with llama-cpp-python backend.
Runs entirely locally on GPU (CUDA) with CPU fallback.

Pipeline Flow:
    1. LocalLLM - Load and run GGUF model
    2. TestGenerator - Generate tests from code descriptions
    3. TestPrioritizer - ML-based test prioritization
    4. PytestGenerator - Convert JSON tests to pytest files
"""

from .local_model import LocalLLM, get_llm_instance
from .test_generator import TestGenerator, generate_tests
from .prioritizer import TestPrioritizer, prioritize_tests
from .pytest_generator import PytestGenerator, generate_pytest_file

__all__ = [
    # Model
    'LocalLLM',
    'get_llm_instance',
    # Test Generation
    'TestGenerator',
    'generate_tests',
    # Prioritization
    'TestPrioritizer', 
    'prioritize_tests',
    # Pytest Generation
    'PytestGenerator',
    'generate_pytest_file',
]

__version__ = '1.0.0'
