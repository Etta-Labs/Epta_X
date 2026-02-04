"""
Impact Analysis Predictor Module
Loads the PKL model and provides prediction functionality for commit risk analysis.
"""

import os
import pickle
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

# Feature definitions based on the training data
CATEGORICAL_FEATURES = [
    'repo_type',
    'module_name', 
    'change_type',
    'component_type',
    'function_category',
    'test_coverage_level'
]

NUMERICAL_FEATURES = [
    'lines_changed',
    'files_changed',
    'dependency_depth',
    'shared_component',  # Boolean -> will be converted to int
    'historical_failure_count',
    'historical_change_frequency',
    'days_since_last_failure',
    'tests_impacted'
]

# Valid values for categorical features
REPO_TYPES = ['monolith', 'microservices']
CHANGE_TYPES = ['API_CHANGE', 'UI_CHANGE', 'SERVICE_LOGIC_CHANGE', 'CONFIG_CHANGE']
COMPONENT_TYPES = ['API', 'UI', 'SERVICE']
FUNCTION_CATEGORIES = ['auth', 'payment', 'search', 'profile', 'analytics', 'admin', 'misc']
TEST_COVERAGE_LEVELS = ['low', 'medium', 'high']
FAILURE_SEVERITIES = ['none', 'low', 'medium', 'high']

# Module names from training data (partial list - model handles one-hot encoding)
KNOWN_MODULES = [
    'OAuthProvider', 'NotificationPrefs', 'SubscriptionManager', 'TransactionProcessor',
    'FilterService', 'SharedLibrary', 'UserAuthenticator', 'RankingAlgorithm',
    'PermissionValidator', 'SupportService', 'FacetProcessor', 'DashboardService',
    'PaymentGateway', 'CoreModule', 'BaseController', 'CredentialStore',
    'TokenManager', 'LoginHandler', 'TrendAnalyzer', 'SearchEngine',
    'AccountSettings', 'HelperFunctions', 'IndexManager', 'FeatureFlagService',
    'UtilityService', 'ProfileValidator', 'DataAggregator', 'RefundHandler',
    'UserManager', 'AuditLogger', 'ProfileService', 'AutocompleteHandler',
    'InsightsProcessor', 'AnalyticsEngine', 'PrivacyController', 'BillingService',
    'SessionController', 'WalletService', 'MetricsCollector', 'PayoutController',
    'AvatarHandler', 'EventTracker', 'SystemMonitor', 'AdminConsole',
    'ConfigManager', 'CommonUtils', 'RoleController', 'MaintenanceHandler',
    'CacheManager', 'AuthService', 'QueryOptimizer', 'DataExporter',
    'GenericHandler', 'ReportGenerator', 'InvoiceGenerator', 'UserPreferences'
]

# Cached model instance
_model_cache = None
_model_path = None


def get_model_path() -> str:
    """Get the path to the model file."""
    # Traverse up to find the model folder
    current_dir = Path(__file__).parent.parent  # backend/
    model_path = current_dir / 'model' / 'impact_analysis_model.pkl'
    return str(model_path)


def load_model():
    """Load the PKL model with caching."""
    global _model_cache, _model_path
    
    model_path = get_model_path()
    
    # Return cached model if already loaded
    if _model_cache is not None and _model_path == model_path:
        return _model_cache
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at: {model_path}")
    
    with open(model_path, 'rb') as f:
        _model_cache = pickle.load(f)
        _model_path = model_path
    
    return _model_cache


def infer_module_from_path(file_paths: List[str]) -> str:
    """Infer module name from file paths."""
    if not file_paths:
        return 'GenericHandler'
    
    # Extract potential module names from paths
    for path in file_paths:
        parts = path.replace('\\', '/').split('/')
        for part in parts:
            # Check against known modules
            for module in KNOWN_MODULES:
                if module.lower() in part.lower():
                    return module
    
    # Default based on path patterns
    path_str = ' '.join(file_paths).lower()
    if 'auth' in path_str or 'login' in path_str or 'oauth' in path_str:
        return 'AuthService'
    elif 'payment' in path_str or 'billing' in path_str:
        return 'PaymentGateway'
    elif 'search' in path_str or 'query' in path_str:
        return 'SearchEngine'
    elif 'profile' in path_str or 'user' in path_str:
        return 'ProfileService'
    elif 'admin' in path_str:
        return 'AdminConsole'
    elif 'analytics' in path_str or 'metric' in path_str:
        return 'AnalyticsEngine'
    elif 'config' in path_str or 'setting' in path_str:
        return 'ConfigManager'
    
    return 'GenericHandler'


def infer_function_category(module_name: str, file_paths: List[str]) -> str:
    """Infer function category from module name and file paths."""
    module_lower = module_name.lower()
    
    # Auth related
    if any(x in module_lower for x in ['auth', 'login', 'oauth', 'credential', 'token', 'session', 'permission']):
        return 'auth'
    # Payment related
    elif any(x in module_lower for x in ['payment', 'billing', 'subscription', 'transaction', 'wallet', 'payout', 'refund', 'invoice']):
        return 'payment'
    # Search related
    elif any(x in module_lower for x in ['search', 'query', 'filter', 'ranking', 'autocomplete', 'facet', 'index', 'cache']):
        return 'search'
    # Profile related
    elif any(x in module_lower for x in ['profile', 'avatar', 'user', 'notification', 'privacy', 'account', 'data']):
        return 'profile'
    # Analytics related
    elif any(x in module_lower for x in ['analytics', 'metric', 'insight', 'trend', 'dashboard', 'report', 'event']):
        return 'analytics'
    # Admin related
    elif any(x in module_lower for x in ['admin', 'role', 'audit', 'maintenance', 'feature', 'config', 'system', 'monitor']):
        return 'admin'
    
    return 'misc'


def infer_component_type(change_type: str, file_paths: List[str]) -> str:
    """Infer component type from change type and file paths."""
    if change_type == 'UI_CHANGE':
        return 'UI'
    elif change_type == 'API_CHANGE':
        return 'API'
    elif change_type in ['SERVICE_LOGIC_CHANGE', 'CONFIG_CHANGE']:
        # Check file paths for hints
        path_str = ' '.join(file_paths).lower() if file_paths else ''
        if 'api' in path_str or 'route' in path_str or 'endpoint' in path_str:
            return 'API'
        elif 'ui' in path_str or 'view' in path_str or 'component' in path_str:
            return 'UI'
        return 'SERVICE'
    
    return 'SERVICE'


def infer_change_type(file_paths: List[str]) -> str:
    """Infer change type from file paths."""
    if not file_paths:
        return 'SERVICE_LOGIC_CHANGE'
    
    path_str = ' '.join(file_paths).lower()
    
    # UI changes
    if any(x in path_str for x in ['.html', '.css', '.vue', '.jsx', '.tsx', 'component', 'view', 'template', 'static/style']):
        return 'UI_CHANGE'
    # Config changes
    elif any(x in path_str for x in ['.json', '.yaml', '.yml', '.env', 'config', 'setting']):
        return 'CONFIG_CHANGE'
    # API changes
    elif any(x in path_str for x in ['api', 'route', 'endpoint', 'controller']):
        return 'API_CHANGE'
    
    return 'SERVICE_LOGIC_CHANGE'


def infer_repo_type(file_paths: List[str], repo_name: str = '') -> str:
    """Infer repository type from file structure."""
    path_str = ' '.join(file_paths).lower() if file_paths else ''
    repo_lower = repo_name.lower()
    
    # Microservices indicators
    if any(x in path_str or x in repo_lower for x in ['service/', '/services/', 'microservice', 'lambda', 'function/']):
        return 'microservices'
    
    # Default to monolith for most cases
    return 'monolith'


def estimate_test_coverage(file_paths: List[str], tests_impacted: int) -> str:
    """Estimate test coverage level."""
    if tests_impacted >= 50:
        return 'high'
    elif tests_impacted >= 10:
        return 'medium'
    return 'low'


def extract_features_from_analysis(
    analysis_data: Dict[str, Any],
    repo_full_name: str = '',
    historical_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Extract features from commit analysis data.
    
    Args:
        analysis_data: The analysis result from diff_analyzer
        repo_full_name: Repository full name
        historical_data: Optional historical metrics
    
    Returns:
        Dictionary with all required features
    """
    # Get summary data
    summary = analysis_data.get('summary', {})
    files = analysis_data.get('files', [])
    
    # Extract file paths
    file_paths = [f.get('path', '') for f in files if isinstance(f, dict)]
    
    # Numerical features
    lines_added = summary.get('lines_added', 0) or 0
    lines_removed = summary.get('lines_removed', 0) or 0
    lines_changed = lines_added + lines_removed
    files_changed = summary.get('files_changed', len(files)) or 0
    
    # Calculate dependency depth (estimate from file paths)
    max_depth = 0
    for path in file_paths:
        depth = len(path.replace('\\', '/').split('/')) - 1
        max_depth = max(max_depth, depth)
    dependency_depth = min(max_depth, 10)
    
    # Check for shared components
    shared_component = any(
        x in path.lower() for path in file_paths 
        for x in ['shared', 'common', 'util', 'lib', 'core', 'base']
    )
    
    # Historical data (use defaults if not provided)
    hist = historical_data or {}
    historical_failure_count = hist.get('failure_count', 5)
    historical_change_frequency = hist.get('change_frequency', 5)
    days_since_last_failure = hist.get('days_since_failure', 180)
    tests_impacted = hist.get('tests_impacted', max(1, files_changed * 3))
    
    # Infer categorical features
    change_type = infer_change_type(file_paths)
    component_type = infer_component_type(change_type, file_paths)
    module_name = infer_module_from_path(file_paths)
    function_category = infer_function_category(module_name, file_paths)
    repo_type = infer_repo_type(file_paths, repo_full_name)
    test_coverage_level = estimate_test_coverage(file_paths, tests_impacted)
    
    return {
        # Numerical features
        'lines_changed': lines_changed,
        'files_changed': files_changed,
        'dependency_depth': dependency_depth,
        'shared_component': 1 if shared_component else 0,
        'historical_failure_count': historical_failure_count,
        'historical_change_frequency': historical_change_frequency,
        'days_since_last_failure': days_since_last_failure,
        'tests_impacted': tests_impacted,
        # Categorical features
        'repo_type': repo_type,
        'module_name': module_name,
        'change_type': change_type,
        'component_type': component_type,
        'function_category': function_category,
        'test_coverage_level': test_coverage_level
    }


def predict_risk(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make a prediction using the loaded model.
    
    Args:
        features: Dictionary containing all required features
    
    Returns:
        Dictionary with prediction results
    """
    # Log input features
    print(f"[IMPACT PREDICTOR] Input features: {features}")
    
    try:
        model = load_model()
        print(f"[IMPACT PREDICTOR] Model loaded successfully: {type(model)}")
    except FileNotFoundError as e:
        print(f"[IMPACT PREDICTOR] Model not found: {e}")
        # Return a default prediction if model is not available
        return {
            'failure_occurred': 0,
            'failure_severity': 'none',
            'risk_score': 20,
            'risk_level': 'LOW',
            'error': str(e)
        }
    
    try:
        # Prepare features for the model
        # The model expects a specific format based on training
        import pandas as pd
        
        # Create a single-row DataFrame
        df = pd.DataFrame([features])
        print(f"[IMPACT PREDICTOR] DataFrame created with columns: {list(df.columns)}")
        
        # Make prediction
        if hasattr(model, 'predict'):
            prediction = model.predict(df)
            print(f"[IMPACT PREDICTOR] Raw prediction output: {prediction}")
            print(f"[IMPACT PREDICTOR] Prediction shape: {prediction.shape if hasattr(prediction, 'shape') else 'N/A'}")
            
            # Handle different model output formats
            if hasattr(prediction, 'shape') and len(prediction.shape) > 1:
                # Multi-output model
                failure_occurred = int(prediction[0][0]) if prediction.shape[1] > 0 else 0
                failure_severity_idx = int(prediction[0][1]) if prediction.shape[1] > 1 else 0
                print(f"[IMPACT PREDICTOR] Multi-output: failure_occurred={failure_occurred}, severity_idx={failure_severity_idx}")
            else:
                # Single output (assume failure_occurred)
                failure_occurred = int(prediction[0]) if len(prediction) > 0 else 0
                failure_severity_idx = 0
                print(f"[IMPACT PREDICTOR] Single output: failure_occurred={failure_occurred}")
            
            # Map severity index to label
            severity_map = {0: 'none', 1: 'low', 2: 'medium', 3: 'high'}
            failure_severity = severity_map.get(failure_severity_idx, 'none')
            print(f"[IMPACT PREDICTOR] Mapped failure_severity: {failure_severity}")
            
            # If model has predict_proba, use it for risk score
            if hasattr(model, 'predict_proba'):
                try:
                    proba = model.predict_proba(df)
                    print(f"[IMPACT PREDICTOR] Probability output: {proba}")
                    if isinstance(proba, list) and len(proba) > 0:
                        # Multi-output: use failure probability
                        risk_score = float(proba[0][0][1]) * 100 if len(proba[0][0]) > 1 else 50
                    else:
                        risk_score = float(proba[0][1]) * 100 if len(proba[0]) > 1 else 50
                    print(f"[IMPACT PREDICTOR] Risk score from proba: {risk_score}")
                except Exception as proba_err:
                    print(f"[IMPACT PREDICTOR] Error getting proba: {proba_err}")
                    risk_score = calculate_risk_score(failure_occurred, failure_severity, features)
            else:
                risk_score = calculate_risk_score(failure_occurred, failure_severity, features)
                print(f"[IMPACT PREDICTOR] Risk score from calculate: {risk_score}")
        else:
            # Fallback for non-standard models
            print(f"[IMPACT PREDICTOR] Model has no predict method, using fallback")
            failure_occurred = 0
            failure_severity = 'none'
            risk_score = calculate_risk_score(failure_occurred, failure_severity, features)
        
        # Determine risk level
        risk_level = get_risk_level(failure_severity, failure_occurred)
        
        result = {
            'failure_occurred': failure_occurred,
            'failure_severity': failure_severity,
            'risk_score': round(risk_score, 1),
            'risk_level': risk_level
        }
        print(f"[IMPACT PREDICTOR] Final prediction result: {result}")
        return result
        
    except Exception as e:
        print(f"[IMPACT PREDICTOR] Exception during prediction: {e}")
        import traceback
        traceback.print_exc()
        # Return a calculated prediction based on features if model fails
        return calculate_fallback_prediction(features, str(e))


def calculate_risk_score(failure_occurred: int, failure_severity: str, features: Dict) -> float:
    """Calculate a risk score based on prediction and features."""
    base_score = 0
    
    if failure_occurred == 0:
        # No failure predicted - low risk
        base_score = 15
        # Adjust based on features
        if features.get('lines_changed', 0) > 500:
            base_score += 10
        if features.get('files_changed', 0) > 10:
            base_score += 5
        if features.get('shared_component', 0):
            base_score += 5
    else:
        # Failure predicted
        if failure_severity == 'low':
            base_score = 40
        elif failure_severity == 'medium':
            base_score = 65
        elif failure_severity == 'high':
            base_score = 85
        else:
            base_score = 35
        
        # Additional adjustments
        if features.get('test_coverage_level') == 'low':
            base_score += 5
        if features.get('historical_failure_count', 0) > 50:
            base_score += 5
    
    return min(max(base_score, 0), 100)


def get_risk_level(failure_severity: str, failure_occurred: int = 0) -> str:
    """Get risk level label based on failure severity."""
    if failure_occurred == 0 or failure_severity == 'none':
        return 'NONE'
    elif failure_severity == 'low':
        return 'LOW'
    elif failure_severity == 'medium':
        return 'MEDIUM'
    elif failure_severity == 'high':
        return 'HIGH'
    return 'LOW'


def calculate_fallback_prediction(features: Dict, error: str = '') -> Dict[str, Any]:
    """Calculate a fallback prediction when the model fails."""
    # Use heuristics based on features
    risk_score = 20  # Base low risk
    
    lines = features.get('lines_changed', 0)
    files = features.get('files_changed', 0)
    shared = features.get('shared_component', 0)
    hist_failures = features.get('historical_failure_count', 0)
    coverage = features.get('test_coverage_level', 'medium')
    change_type = features.get('change_type', '')
    
    # Increase risk for large changes
    if lines > 1000:
        risk_score += 25
    elif lines > 500:
        risk_score += 15
    elif lines > 100:
        risk_score += 5
    
    # Increase risk for many files
    if files > 20:
        risk_score += 15
    elif files > 10:
        risk_score += 8
    
    # Shared components are riskier
    if shared:
        risk_score += 10
    
    # Historical failures matter
    if hist_failures > 100:
        risk_score += 15
    elif hist_failures > 50:
        risk_score += 10
    elif hist_failures > 20:
        risk_score += 5
    
    # Low test coverage is risky
    if coverage == 'low':
        risk_score += 10
    elif coverage == 'high':
        risk_score -= 5
    
    # API changes are riskier
    if change_type == 'API_CHANGE':
        risk_score += 5
    elif change_type == 'CONFIG_CHANGE':
        risk_score += 8
    
    # Cap the score
    risk_score = min(max(risk_score, 5), 95)
    
    # Determine failure prediction
    if risk_score >= 70:
        failure_occurred = 1
        failure_severity = 'high' if risk_score >= 80 else 'medium'
    elif risk_score >= 50:
        failure_occurred = 1
        failure_severity = 'medium' if risk_score >= 60 else 'low'
    elif risk_score >= 35:
        failure_occurred = 1
        failure_severity = 'low'
    else:
        failure_occurred = 0
        failure_severity = 'none'
    
    return {
        'failure_occurred': failure_occurred,
        'failure_severity': failure_severity,
        'risk_score': round(risk_score, 1),
        'risk_level': get_risk_level(failure_severity, failure_occurred),
        'fallback': True,
        'error': error if error else None
    }


def analyze_commit(
    analysis_data: Dict[str, Any],
    repo_full_name: str = '',
    historical_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Main entry point: Analyze a commit and return risk prediction.
    
    Args:
        analysis_data: The analysis result from diff_analyzer
        repo_full_name: Repository full name
        historical_data: Optional historical metrics
    
    Returns:
        Complete prediction result with features and prediction
    """
    # Extract features
    features = extract_features_from_analysis(analysis_data, repo_full_name, historical_data)
    
    # Make prediction
    prediction = predict_risk(features)
    
    return {
        'features': features,
        'prediction': prediction,
        'analysis_summary': {
            'lines_changed': features['lines_changed'],
            'files_changed': features['files_changed'],
            'change_type': features['change_type'],
            'component_type': features['component_type'],
            'module_name': features['module_name'],
            'function_category': features['function_category']
        }
    }
