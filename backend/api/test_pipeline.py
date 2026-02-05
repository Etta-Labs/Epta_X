"""
Test Generation Pipeline API
=============================
API endpoints for the ETTA-X test generation pipeline.

Pipeline Flow:
1. Generate tests from code description (LLM)
2. Prioritize tests (ML)
3. Generate pytest files
4. Execute tests (CI/CD)
5. Store and return results
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/tests", tags=["test-generation"])


# ==================== PYDANTIC MODELS ====================

class TestGenerationRequest(BaseModel):
    """Request to generate tests from code description."""
    code_description: str = Field(..., min_length=10, description="Description of the code/API to test")
    language: str = Field(default="python", description="Target language")
    repository: Optional[str] = Field(default=None, description="Repository name")
    commit: Optional[str] = Field(default=None, description="Commit SHA")
    change_risk_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Risk score from impact analysis")
    files_changed: int = Field(default=1, ge=0, description="Number of files changed")
    critical_module: bool = Field(default=False, description="Whether changes affect critical module")


class TestExecutionRequest(BaseModel):
    """Request to execute generated tests."""
    test_file: str = Field(..., description="Path to test file to execute")
    base_url: Optional[str] = Field(default="http://localhost:8000", description="Base URL for API tests")
    coverage: bool = Field(default=True, description="Whether to collect coverage")
    verbose: bool = Field(default=True, description="Verbose output")


class TestRunResult(BaseModel):
    """Result of a test run."""
    run_id: str
    status: str  # pending, running, completed, failed
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    coverage: Optional[float] = None
    duration_ms: float = 0
    failed_tests: List[Dict[str, Any]] = []
    output: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ==================== IN-MEMORY STORAGE ====================

# Store test runs (in production, use database)
test_runs: Dict[str, Dict[str, Any]] = {}
generated_tests_cache: Dict[str, Dict[str, Any]] = {}


# ==================== LLM MODEL STATUS ====================

_llm_loaded = False
_llm_status = {
    "loaded": False,
    "using_gpu": False,
    "model_name": "CodeLlama-7B-Instruct-GGUF",
    "error": None
}


def get_llm_module():
    """Lazy import of LLM module to avoid startup delays."""
    global _llm_loaded, _llm_status
    
    try:
        from backend.model.LLM import (
            get_llm_instance,
            generate_tests,
            prioritize_tests,
            generate_pytest_file
        )
        return {
            "get_llm_instance": get_llm_instance,
            "generate_tests": generate_tests,
            "prioritize_tests": prioritize_tests,
            "generate_pytest_file": generate_pytest_file
        }
    except ImportError as e:
        logger.error(f"Failed to import LLM module: {e}")
        _llm_status["error"] = str(e)
        return None


# ==================== API ENDPOINTS ====================

@router.get("/status")
async def get_test_pipeline_status():
    """
    Get the status of the test generation pipeline.
    """
    global _llm_status
    
    llm_module = get_llm_module()
    
    if llm_module:
        try:
            llm = llm_module["get_llm_instance"]()
            _llm_status = llm.get_status()
        except Exception as e:
            _llm_status["error"] = str(e)
    
    return {
        "pipeline_status": "ready" if llm_module else "not_ready",
        "llm_status": _llm_status,
        "active_runs": len([r for r in test_runs.values() if r.get("status") == "running"]),
        "total_runs": len(test_runs),
        "cached_tests": len(generated_tests_cache)
    }


@router.post("/generate")
async def generate_tests_endpoint(request: TestGenerationRequest):
    """
    Generate tests from code description using local LLM.
    
    Returns prioritized tests ready for execution.
    """
    llm_module = get_llm_module()
    
    if not llm_module:
        raise HTTPException(
            status_code=503,
            detail="LLM module not available. Please install llama-cpp-python."
        )
    
    try:
        # Step 1: Generate tests using LLM
        logger.info(f"Generating tests for: {request.code_description[:100]}...")
        
        generation_result = llm_module["generate_tests"](
            code_description=request.code_description,
            language=request.language
        )
        
        if not generation_result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=f"Test generation failed: {generation_result.get('error')}"
            )
        
        tests = generation_result.get("tests", [])
        
        if not tests:
            return {
                "success": False,
                "message": "No tests generated",
                "tests": [],
                "prioritized_tests": [],
                "generation_time_ms": generation_result.get("generation_time_ms", 0)
            }
        
        # Step 2: Prioritize tests
        logger.info(f"Prioritizing {len(tests)} tests...")
        
        prioritization_result = llm_module["prioritize_tests"](
            tests=tests,
            change_risk_score=request.change_risk_score,
            files_changed=request.files_changed,
            critical_module=request.critical_module
        )
        
        # Cache the results
        cache_key = f"{request.repository or 'unknown'}_{request.commit or datetime.now().isoformat()}"
        generated_tests_cache[cache_key] = {
            "tests": tests,
            "prioritized": prioritization_result,
            "request": request.dict(),
            "generated_at": datetime.now().isoformat()
        }
        
        return {
            "success": True,
            "cache_key": cache_key,
            "generation": {
                "test_count": len(tests),
                "generation_time_ms": generation_result.get("generation_time_ms", 0),
                "model_used": generation_result.get("model_used", "CodeLlama-7B")
            },
            "prioritization": {
                "total_count": prioritization_result.get("total_count", 0),
                "selected_count": prioritization_result.get("selected_count", 0),
                "priority_level": prioritization_result.get("priority_level", "all"),
                "risk_context": prioritization_result.get("risk_context", {})
            },
            "all_tests": prioritization_result.get("all_tests", []),
            "selected_tests": prioritization_result.get("selected_tests", [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-file")
async def generate_pytest_file_endpoint(
    cache_key: str,
    filename: Optional[str] = None,
    base_url: str = "http://localhost:8000"
):
    """
    Generate pytest file from cached test results.
    """
    if cache_key not in generated_tests_cache:
        raise HTTPException(status_code=404, detail="Cache key not found. Generate tests first.")
    
    llm_module = get_llm_module()
    if not llm_module:
        raise HTTPException(status_code=503, detail="LLM module not available")
    
    try:
        cached = generated_tests_cache[cache_key]
        prioritized = cached.get("prioritized", {})
        selected_tests = prioritized.get("selected_tests", [])
        request_data = cached.get("request", {})
        
        if not selected_tests:
            raise HTTPException(status_code=400, detail="No tests to generate file from")
        
        # Generate pytest file
        result = llm_module["generate_pytest_file"](
            tests=selected_tests,
            filename=filename,
            base_url=base_url,
            repository=request_data.get("repository", "unknown"),
            commit=request_data.get("commit", "unknown")
        )
        
        return {
            "success": True,
            "files": result,
            "test_count": result.get("test_count", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pytest file generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute")
async def execute_tests_endpoint(
    request: TestExecutionRequest,
    background_tasks: BackgroundTasks
):
    """
    Execute generated tests and return results.
    Runs in background for long-running test suites.
    """
    import uuid
    
    run_id = str(uuid.uuid4())[:8]
    
    # Initialize run record
    test_runs[run_id] = {
        "run_id": run_id,
        "status": "pending",
        "test_file": request.test_file,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "coverage": None,
        "duration_ms": 0,
        "failed_tests": [],
        "output": "",
        "started_at": None,
        "completed_at": None
    }
    
    # Run tests in background
    background_tasks.add_task(
        run_pytest_async,
        run_id,
        request.test_file,
        request.base_url,
        request.coverage,
        request.verbose
    )
    
    return {
        "run_id": run_id,
        "status": "pending",
        "message": "Test execution started"
    }


async def run_pytest_async(
    run_id: str,
    test_file: str,
    base_url: str,
    coverage: bool,
    verbose: bool
):
    """
    Run pytest asynchronously and update results.
    """
    import time
    
    test_runs[run_id]["status"] = "running"
    test_runs[run_id]["started_at"] = datetime.now().isoformat()
    
    start_time = time.time()
    
    try:
        # Build pytest command
        cmd = ["pytest", test_file, "--json-report", "--json-report-file=-"]
        
        if coverage:
            cmd.extend(["--cov", "--cov-report=json"])
        
        if verbose:
            cmd.append("-v")
        
        # Set environment
        env = os.environ.copy()
        env["TEST_BASE_URL"] = base_url
        
        # Run pytest
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        stdout, stderr = await process.communicate()
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Parse results
        output = stdout.decode() + stderr.decode()
        test_runs[run_id]["output"] = output
        test_runs[run_id]["duration_ms"] = duration_ms
        
        # Try to parse JSON report
        try:
            # Look for JSON in output
            import re
            json_match = re.search(r'\{.*"summary".*\}', output, re.DOTALL)
            if json_match:
                report = json.loads(json_match.group())
                summary = report.get("summary", {})
                
                test_runs[run_id]["total_tests"] = summary.get("total", 0)
                test_runs[run_id]["passed"] = summary.get("passed", 0)
                test_runs[run_id]["failed"] = summary.get("failed", 0)
                test_runs[run_id]["skipped"] = summary.get("skipped", 0)
                
                # Extract failed test details
                if "tests" in report:
                    failed_tests = [
                        {
                            "name": t.get("nodeid", ""),
                            "outcome": t.get("outcome", ""),
                            "message": t.get("call", {}).get("crash", {}).get("message", "")
                        }
                        for t in report["tests"]
                        if t.get("outcome") == "failed"
                    ]
                    test_runs[run_id]["failed_tests"] = failed_tests
        except:
            # Fallback: parse output manually
            pass
        
        # Parse coverage if available
        coverage_file = Path("coverage.json")
        if coverage_file.exists():
            try:
                with open(coverage_file) as f:
                    cov_data = json.load(f)
                    test_runs[run_id]["coverage"] = cov_data.get("totals", {}).get("percent_covered", 0)
            except:
                pass
        
        test_runs[run_id]["status"] = "completed" if process.returncode == 0 else "failed"
        
    except Exception as e:
        logger.error(f"Test execution error: {e}")
        test_runs[run_id]["status"] = "failed"
        test_runs[run_id]["output"] = str(e)
    
    test_runs[run_id]["completed_at"] = datetime.now().isoformat()


@router.get("/runs")
async def get_test_runs():
    """
    Get all test runs.
    """
    runs = list(test_runs.values())
    runs.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return {
        "total": len(runs),
        "runs": runs[:50]  # Return last 50 runs
    }


@router.get("/runs/{run_id}")
async def get_test_run(run_id: str):
    """
    Get a specific test run by ID.
    """
    if run_id not in test_runs:
        raise HTTPException(status_code=404, detail="Test run not found")
    
    return test_runs[run_id]


@router.get("/cache")
async def get_cached_tests():
    """
    Get all cached test generation results.
    """
    return {
        "total": len(generated_tests_cache),
        "cache_keys": list(generated_tests_cache.keys()),
        "entries": [
            {
                "key": key,
                "test_count": len(data.get("tests", [])),
                "generated_at": data.get("generated_at")
            }
            for key, data in generated_tests_cache.items()
        ]
    }


@router.get("/cache/{cache_key}")
async def get_cached_test(cache_key: str):
    """
    Get cached test generation result.
    """
    if cache_key not in generated_tests_cache:
        raise HTTPException(status_code=404, detail="Cache key not found")
    
    return generated_tests_cache[cache_key]


@router.delete("/cache/{cache_key}")
async def delete_cached_test(cache_key: str):
    """
    Delete a cached test generation result.
    """
    if cache_key not in generated_tests_cache:
        raise HTTPException(status_code=404, detail="Cache key not found")
    
    del generated_tests_cache[cache_key]
    return {"message": "Cache entry deleted"}


@router.post("/load-model")
async def load_llm_model(force_cpu: bool = False):
    """
    Pre-load the LLM model into memory.
    Model will be auto-downloaded from HuggingFace if not present.
    """
    llm_module = get_llm_module()
    
    if not llm_module:
        raise HTTPException(status_code=503, detail="LLM module not available. Install ctransformers.")
    
    try:
        llm = llm_module["get_llm_instance"]()
        success = llm.load(force_cpu=force_cpu)
        
        if success:
            return {
                "success": True,
                "status": llm.get_status()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to load model")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download-model")
async def download_llm_model():
    """
    Download the LLM model from HuggingFace.
    """
    llm_module = get_llm_module()
    
    if not llm_module:
        raise HTTPException(status_code=503, detail="LLM module not available")
    
    try:
        llm = llm_module["get_llm_instance"]()
        success = llm.download_model()
        
        if success:
            return {
                "success": True,
                "message": "Model downloaded successfully",
                "status": llm.get_status()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to download model")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/generated")
async def get_generated_tests():
    """
    Get all generated tests from webhook events.
    This fetches tests that were auto-generated during pipeline processing.
    """
    import sqlite3
    import json
    
    db_path = Path(__file__).parent.parent / "data" / "etta_x.db"
    
    if not db_path.exists():
        return {"total": 0, "tests": []}
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Get all processed events with test generation results
        # Using correct column names: repository_full_name, processed (boolean)
        cursor.execute('''
            SELECT id, repository_full_name, commit_sha, branch, processed, processing_result, created_at
            FROM webhook_events
            WHERE processed = 1 AND processing_result IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 50
        ''')
        
        events = cursor.fetchall()
        conn.close()
        
        all_tests = []
        for event in events:
            event_id, repo, commit, branch, processed, result_json, created_at = event
            
            try:
                result = json.loads(result_json)
                if not result or not isinstance(result, dict):
                    continue
                    
                test_gen = result.get('test_generation')
                if not test_gen or not isinstance(test_gen, dict):
                    continue
                
                # Check for tests - handle both success=True and tests list directly
                tests = test_gen.get('tests', [])
                if not tests:
                    continue
                    
                selected = test_gen.get('selected_tests', [])
                
                for test in tests:
                    if not isinstance(test, dict):
                        continue
                    test_copy = test.copy()
                    test_copy['event_id'] = event_id
                    test_copy['repository'] = repo
                    test_copy['commit'] = commit[:7] if commit else None
                    test_copy['branch'] = branch
                    test_copy['generated_at'] = created_at
                    test_copy['is_selected'] = test in selected
                    all_tests.append(test_copy)
                        
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
        
        return {
            "total": len(all_tests),
            "tests": all_tests
        }
        
    except Exception as e:
        logger.error(f"Error fetching generated tests: {e}")
        return {"total": 0, "tests": [], "error": str(e)}
