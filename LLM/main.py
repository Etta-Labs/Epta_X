"""
LLM Gateway - FastAPI Application

This service acts as a gateway between clients and the Colab GPU worker.
It handles:
- Worker registration (Colab registers its Cloudflare tunnel URL)
- Health checks and worker status
- Request forwarding to the LLM worker
- Test generation endpoint
"""
import logging
import json
import re
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings, get_worker_url, set_worker_url, clear_worker_url
from colab_client import worker_client
from models import (
    HealthResponse, WorkerStatus, WorkerRegisterRequest, WorkerRegisterResponse,
    GenerateTestsRequest, GenerateTestsResponse, GeneratedTest,
    CompletionRequest, CompletionResponse
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    yield
    # Cleanup
    await worker_client.close()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Gateway service for LLM inference via Colab GPU worker",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Security
# ============================================================================

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key if configured."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Gateway health check.
    Also reports the current worker status.
    """
    worker_health = await worker_client.health_check()
    worker_url = get_worker_url()
    
    if worker_health["healthy"]:
        worker_status = WorkerStatus.ONLINE
    elif worker_health["status"] == "no_worker_registered":
        worker_status = WorkerStatus.OFFLINE
    elif worker_health["status"] == "timeout":
        worker_status = WorkerStatus.STARTING
    else:
        worker_status = WorkerStatus.ERROR
    
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        worker_status=worker_status,
        worker_url=worker_url if worker_health["healthy"] else None
    )


@app.get("/worker-status")
async def worker_status():
    """
    Detailed worker status check.
    Returns more information than the basic health endpoint.
    """
    health = await worker_client.health_check()
    inactivity = worker_client.get_inactivity_seconds()
    
    return {
        "worker": health,
        "inactivity_seconds": inactivity,
        "inactivity_timeout_minutes": settings.inactivity_timeout_minutes,
        "registered_url": get_worker_url()
    }


# ============================================================================
# Worker Registration
# ============================================================================

@app.post("/register-worker", response_model=WorkerRegisterResponse)
async def register_worker(request: WorkerRegisterRequest):
    """
    Register a Colab worker's Cloudflare tunnel URL.
    
    Called by the Colab notebook after it starts the llama-server
    and establishes the Cloudflare tunnel.
    """
    logger.info(f"Registering worker URL: {request.worker_url}")
    
    # Validate URL format
    if not request.worker_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="Worker URL must use HTTPS (Cloudflare tunnel URLs do)"
        )
    
    # Save the worker URL
    set_worker_url(request.worker_url)
    
    # Verify the worker is actually reachable
    health = await worker_client.health_check()
    
    if health["healthy"]:
        logger.info(f"Worker registered and verified: {request.worker_url}")
        return WorkerRegisterResponse(
            success=True,
            message=f"Worker registered successfully. Model: {request.model_name or 'unknown'}"
        )
    else:
        logger.warning(f"Worker registered but health check failed: {health}")
        return WorkerRegisterResponse(
            success=True,
            message=f"Worker URL registered, but health check failed: {health['message']}"
        )


@app.post("/unregister-worker")
async def unregister_worker():
    """
    Unregister the current worker.
    Called when the Colab notebook shuts down.
    """
    clear_worker_url()
    logger.info("Worker unregistered")
    return {"success": True, "message": "Worker unregistered"}


# ============================================================================
# LLM Endpoints
# ============================================================================

@app.post("/generate-tests", response_model=GenerateTestsResponse)
async def generate_tests(
    request: GenerateTestsRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Generate unit tests for the provided code using the LLM.
    
    This endpoint:
    1. Checks if the worker is available
    2. Constructs a prompt for test generation
    3. Forwards the request to the Colab worker
    4. Parses the response and returns structured tests
    """
    # Check worker health first
    health = await worker_client.health_check()
    
    if not health["healthy"]:
        if health["status"] == "no_worker_registered":
            raise HTTPException(
                status_code=503,
                detail="No LLM worker available. Please start the Colab notebook first."
            )
        else:
            raise HTTPException(
                status_code=503,
                detail=f"LLM worker is not healthy: {health['message']}"
            )
    
    # Build the test generation prompt
    prompt = build_test_generation_prompt(request)
    
    # Send to worker
    result = await worker_client.generate_completion(
        prompt=prompt,
        max_tokens=request.max_tokens or 2048,
        temperature=request.temperature or 0.3,  # Lower temp for code generation
        stop=["```\n\n", "---"]  # Stop sequences to prevent runaway generation
    )
    
    if not result["success"]:
        return GenerateTestsResponse(
            success=False,
            error=result["error"]
        )
    
    # Parse the LLM response
    try:
        raw_content = result["data"].get("content", "")
        tests = parse_test_response(raw_content, request.language)
        
        return GenerateTestsResponse(
            success=True,
            tests=tests,
            raw_response=raw_content,
            tokens_used=result["data"].get("tokens_predicted")
        )
    except Exception as e:
        logger.exception("Failed to parse test response")
        return GenerateTestsResponse(
            success=False,
            raw_response=result["data"].get("content"),
            error=f"Failed to parse response: {str(e)}"
        )


@app.post("/completion", response_model=CompletionResponse)
async def completion(
    request: CompletionRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Generic completion endpoint for direct LLM access.
    """
    # Check worker health
    health = await worker_client.health_check()
    
    if not health["healthy"]:
        raise HTTPException(
            status_code=503,
            detail=f"LLM worker not available: {health['message']}"
        )
    
    # Forward to worker
    result = await worker_client.generate_completion(
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        stop=request.stop
    )
    
    if not result["success"]:
        return CompletionResponse(
            success=False,
            error=result["error"]
        )
    
    return CompletionResponse(
        success=True,
        content=result["data"].get("content"),
        usage={
            "prompt_tokens": result["data"].get("tokens_evaluated", 0),
            "completion_tokens": result["data"].get("tokens_predicted", 0),
            "total_tokens": result["data"].get("tokens_evaluated", 0) + result["data"].get("tokens_predicted", 0)
        }
    )


# ============================================================================
# Helper Functions
# ============================================================================

def build_test_generation_prompt(request: GenerateTestsRequest) -> str:
    """Build the prompt for test generation."""
    
    framework_hint = ""
    if request.test_framework:
        framework_hint = f"Use the {request.test_framework} testing framework."
    elif request.language.lower() == "python":
        framework_hint = "Use pytest for the tests."
    elif request.language.lower() in ["javascript", "typescript"]:
        framework_hint = "Use Jest for the tests."
    
    additional = ""
    if request.additional_context:
        additional = f"\n\nAdditional instructions: {request.additional_context}"
    
    prompt = f"""You are an expert software engineer. Generate comprehensive unit tests for the following {request.language} code.

{framework_hint}
{additional}

Requirements:
1. Cover all public functions and methods
2. Include edge cases and error handling tests
3. Use descriptive test names
4. Add comments explaining what each test verifies
5. Return the tests in valid {request.language} code

Source Code:
```{request.language}
{request.code}
```

Generated Tests:
```{request.language}
"""
    
    return prompt


def parse_test_response(response: str, language: str) -> list[GeneratedTest]:
    """Parse the LLM response to extract test cases."""
    tests = []
    
    # Try to extract code blocks
    code_pattern = rf"```(?:{language})?\s*(.*?)```"
    code_blocks = re.findall(code_pattern, response, re.DOTALL | re.IGNORECASE)
    
    if code_blocks:
        # Use the first code block as the main test code
        test_code = code_blocks[0].strip()
    else:
        # Use the raw response if no code blocks found
        test_code = response.strip()
    
    # Try to split into individual test functions
    if language.lower() == "python":
        test_pattern = r"(def test_\w+.*?)(?=def test_|\Z)"
        matches = re.findall(test_pattern, test_code, re.DOTALL)
        
        for i, match in enumerate(matches):
            # Extract test name
            name_match = re.search(r"def (test_\w+)", match)
            name = name_match.group(1) if name_match else f"test_{i + 1}"
            
            # Extract docstring as description
            doc_match = re.search(r'"""(.*?)"""', match, re.DOTALL)
            description = doc_match.group(1).strip() if doc_match else f"Test case {i + 1}"
            
            tests.append(GeneratedTest(
                name=name,
                description=description,
                code=match.strip(),
                test_type="unit"
            ))
    
    # Fallback: return as single test if parsing failed
    if not tests and test_code:
        tests.append(GeneratedTest(
            name="generated_tests",
            description="Generated test suite",
            code=test_code,
            test_type="unit"
        ))
    
    return tests


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
