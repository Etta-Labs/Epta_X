"""
Test Prioritization Module
==========================
Integrates with the ML test prioritizer to select important tests.
Combines LLM-generated tests with impact analysis context.

Usage:
    from model.LLM.prioritizer import prioritize_tests
    
    result = prioritize_tests(
        tests=generated_tests,
        change_risk_score=0.82,
        files_changed=3,
        critical_module=True
    )
"""

import os
import sys
import logging
import pickle
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Path to the test prioritizer model
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),  # backend/model/
    "test_prioritizer.pkl"
)


@dataclass
class PrioritizedTest:
    """A test with priority score."""
    name: str
    endpoint: str
    method: str
    payload: Dict[str, Any]
    expected_status: int
    description: str
    priority_score: float
    is_important: bool
    category: str
    rank: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PrioritizationResult:
    """Result of test prioritization."""
    selected_tests: List[PrioritizedTest]
    all_tests: List[PrioritizedTest]
    priority_level: str  # "important", "all"
    total_count: int
    selected_count: int
    risk_context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_tests": [t.to_dict() for t in self.selected_tests],
            "all_tests": [t.to_dict() for t in self.all_tests],
            "priority_level": self.priority_level,
            "total_count": self.total_count,
            "selected_count": self.selected_count,
            "risk_context": self.risk_context
        }


class TestPrioritizer:
    """
    ML-based test prioritization using the trained model.
    
    Features:
    - Loads the test_prioritizer.pkl model
    - Integrates with impact analysis risk scores
    - Provides scored and ranked test lists
    """
    
    # Category to base score mapping (higher = more important)
    CATEGORY_SCORES = {
        "authentication": 0.30,
        "security": 0.28,
        "payment": 0.25,
        "error_handling": 0.20,
        "crud": 0.15,
        "edge_case": 0.12,
        "happy_path": 0.10,
        "functional": 0.08,
    }
    
    # Method priority (affects score)
    METHOD_SCORES = {
        "POST": 0.10,
        "PUT": 0.08,
        "DELETE": 0.08,
        "PATCH": 0.06,
        "GET": 0.04,
    }
    
    def __init__(self, model_path: Optional[str] = None, threshold: float = 0.65):
        """
        Initialize the test prioritizer.
        
        Args:
            model_path: Path to the trained model
            threshold: Score threshold for selecting important tests
        """
        self.model_path = model_path or MODEL_PATH
        self.threshold = threshold
        self.model = None
        self.model_loaded = False
        
        self._try_load_model()
    
    def _try_load_model(self):
        """Try to load the ML model."""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    model_data = pickle.load(f)
                self.model = model_data.get("model")
                self.threshold = model_data.get("threshold", self.threshold)
                self.model_loaded = True
                logger.info(f"Test prioritizer model loaded from {self.model_path}")
            else:
                logger.warning(f"Model not found at {self.model_path}, using heuristic scoring")
        except Exception as e:
            logger.warning(f"Failed to load model: {e}, using heuristic scoring")
    
    def _calculate_heuristic_score(
        self,
        test: Dict[str, Any],
        change_risk_score: float,
        critical_module: bool
    ) -> float:
        """
        Calculate priority score using heuristics when ML model unavailable.
        
        Score components:
        - Category base score (0.08 - 0.30)
        - Method score (0.04 - 0.10)
        - Risk multiplier (change_risk_score affects weight)
        - Critical module boost
        - Status code factor (error tests get boost)
        """
        category = test.get("category", "functional")
        method = test.get("method", "GET").upper()
        expected_status = test.get("expected_status", 200)
        
        # Base score from category
        base_score = self.CATEGORY_SCORES.get(category, 0.08)
        
        # Add method score
        method_score = self.METHOD_SCORES.get(method, 0.04)
        
        # Error status boost
        status_boost = 0.0
        if expected_status >= 400:
            status_boost = 0.10
        elif expected_status >= 300:
            status_boost = 0.03
        
        # Critical module boost
        critical_boost = 0.15 if critical_module else 0.0
        
        # Calculate raw score
        raw_score = base_score + method_score + status_boost + critical_boost
        
        # Apply risk multiplier (higher risk = higher priority)
        risk_multiplier = 0.5 + (change_risk_score * 0.5)  # Range: 0.5 - 1.0
        
        # Final score (capped at 1.0)
        final_score = min(raw_score * risk_multiplier, 1.0)
        
        return round(final_score, 4)
    
    def _calculate_ml_score(
        self,
        test: Dict[str, Any],
        change_risk_score: float,
        critical_module: bool,
        files_changed: int
    ) -> float:
        """Calculate priority score using the ML model."""
        try:
            # Build feature vector matching Z_Data_set/ml/features.py format
            features = {
                "name": test.get("name", ""),
                "endpoint": test.get("endpoint", "/"),
                "method": test.get("method", "GET"),
                "expected_status": test.get("expected_status", 200),
                "change_risk_score": change_risk_score,
                "critical_module": critical_module,
                "files_changed": files_changed,
            }
            
            # Simple feature vector for the model
            # This would need to match the exact feature extraction from ml/features.py
            # For now, we use a simplified approach
            feature_vector = self._extract_model_features(features)
            
            if self.model is not None:
                import numpy as np
                probability = self.model.predict_proba([feature_vector])[0, 1]
                return float(probability)
        except Exception as e:
            logger.warning(f"ML scoring failed: {e}, falling back to heuristics")
        
        # Fallback to heuristics
        return self._calculate_heuristic_score(test, change_risk_score, critical_module)
    
    def _extract_model_features(self, features: Dict[str, Any]) -> List[float]:
        """Extract feature vector for the ML model."""
        # Simplified feature extraction
        # In production, this should match Z_Data_set/ml/features.py exactly
        
        name = features.get("name", "").lower()
        endpoint = features.get("endpoint", "").lower()
        method = features.get("method", "GET")
        status = features.get("expected_status", 200)
        risk = features.get("change_risk_score", 0.5)
        critical = 1.0 if features.get("critical_module") else 0.0
        files = features.get("files_changed", 1)
        
        # Feature: is_auth_test
        is_auth = 1.0 if any(x in name or x in endpoint for x in ['auth', 'login', 'token']) else 0.0
        
        # Feature: is_error_test
        is_error = 1.0 if status >= 400 else 0.0
        
        # Feature: method encoding (one-hot simplified)
        method_post = 1.0 if method == "POST" else 0.0
        method_get = 1.0 if method == "GET" else 0.0
        
        return [
            risk,
            critical,
            float(files),
            is_auth,
            is_error,
            method_post,
            method_get,
            float(status) / 500.0,  # Normalized status
        ]
    
    def prioritize(
        self,
        tests: List[Dict[str, Any]],
        change_risk_score: float = 0.5,
        files_changed: int = 1,
        critical_module: bool = False
    ) -> PrioritizationResult:
        """
        Prioritize tests based on ML model and context.
        
        Args:
            tests: List of test dictionaries from LLM
            change_risk_score: Risk score from impact analysis (0.0-1.0)
            files_changed: Number of files changed
            critical_module: Whether changes affect critical module
            
        Returns:
            PrioritizationResult with scored and selected tests
        """
        if not tests:
            return PrioritizationResult(
                selected_tests=[],
                all_tests=[],
                priority_level="all",
                total_count=0,
                selected_count=0,
                risk_context={
                    "change_risk_score": change_risk_score,
                    "files_changed": files_changed,
                    "critical_module": critical_module
                }
            )
        
        # Calculate scores for all tests
        scored_tests = []
        for test in tests:
            if self.model_loaded:
                score = self._calculate_ml_score(
                    test, change_risk_score, critical_module, files_changed
                )
            else:
                score = self._calculate_heuristic_score(
                    test, change_risk_score, critical_module
                )
            
            scored_tests.append({
                **test,
                "priority_score": score,
                "is_important": score >= self.threshold
            })
        
        # Sort by score (descending)
        scored_tests.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Add rank
        all_prioritized = []
        for rank, test in enumerate(scored_tests, 1):
            all_prioritized.append(PrioritizedTest(
                name=test.get("name", f"test_{rank}"),
                endpoint=test.get("endpoint", "/"),
                method=test.get("method", "GET"),
                payload=test.get("payload", {}),
                expected_status=test.get("expected_status", 200),
                description=test.get("description", ""),
                priority_score=test["priority_score"],
                is_important=test["is_important"],
                category=test.get("category", "functional"),
                rank=rank
            ))
        
        # Select important tests
        selected = [t for t in all_prioritized if t.is_important]
        
        # If no tests selected by threshold, select top 50%
        if not selected and all_prioritized:
            half = max(1, len(all_prioritized) // 2)
            selected = all_prioritized[:half]
        
        priority_level = "important" if selected else "all"
        
        return PrioritizationResult(
            selected_tests=selected,
            all_tests=all_prioritized,
            priority_level=priority_level,
            total_count=len(all_prioritized),
            selected_count=len(selected),
            risk_context={
                "change_risk_score": change_risk_score,
                "files_changed": files_changed,
                "critical_module": critical_module,
                "threshold": self.threshold,
                "model_loaded": self.model_loaded
            }
        )


# Convenience function
def prioritize_tests(
    tests: List[Dict[str, Any]],
    change_risk_score: float = 0.5,
    files_changed: int = 1,
    critical_module: bool = False
) -> Dict[str, Any]:
    """
    Prioritize tests from LLM output.
    
    Args:
        tests: List of test dictionaries
        change_risk_score: Risk score from impact analysis (0.0-1.0)
        files_changed: Number of files changed
        critical_module: Whether changes affect critical module
        
    Returns:
        Dictionary with prioritization results
    """
    prioritizer = TestPrioritizer()
    result = prioritizer.prioritize(
        tests=tests,
        change_risk_score=change_risk_score,
        files_changed=files_changed,
        critical_module=critical_module
    )
    return result.to_dict()


# CLI for testing
if __name__ == "__main__":
    import json
    
    # Sample tests
    sample_tests = [
        {
            "name": "test_valid_login",
            "endpoint": "/login",
            "method": "POST",
            "payload": {"username": "valid", "password": "valid"},
            "expected_status": 200,
            "category": "authentication",
            "description": "Test valid login"
        },
        {
            "name": "test_invalid_password",
            "endpoint": "/login",
            "method": "POST",
            "payload": {"username": "valid", "password": "wrong"},
            "expected_status": 401,
            "category": "authentication",
            "description": "Test invalid password"
        },
        {
            "name": "test_get_products",
            "endpoint": "/products",
            "method": "GET",
            "payload": {},
            "expected_status": 200,
            "category": "crud",
            "description": "Test get products"
        }
    ]
    
    print("="*60)
    print("Test Prioritization Demo")
    print("="*60)
    
    result = prioritize_tests(
        tests=sample_tests,
        change_risk_score=0.82,
        files_changed=3,
        critical_module=True
    )
    
    print(f"\nTotal tests: {result['total_count']}")
    print(f"Selected: {result['selected_count']}")
    print(f"Priority level: {result['priority_level']}")
    print(f"\nRisk context: {result['risk_context']}")
    
    print("\n--- All Tests (ranked) ---")
    for test in result['all_tests']:
        status = "✓" if test['is_important'] else "○"
        print(f"  {status} [{test['rank']}] {test['name']}: {test['priority_score']:.2%}")
    
    print("\n--- Selected Tests ---")
    for test in result['selected_tests']:
        print(f"  • {test['name']} (score: {test['priority_score']:.2%})")
