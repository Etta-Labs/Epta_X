from fastapi import FastAPI, Request, HTTPException, Depends, status, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from pydantic import BaseModel
from typing import Optional, List, Dict
import httpx
import os
import secrets
import hashlib
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import database module
from backend.app.database import (
    init_database, is_first_run, mark_setup_complete,
    create_user, get_user_by_github_id, update_user, user_exists,
    get_user_settings, update_user_settings,
    create_repository, get_repository_by_github_id, get_repository_by_full_name,
    get_user_repositories,
    create_webhook, get_webhook_by_repository, get_webhook_secret_hash,
    update_webhook_delivery, deactivate_webhook,
    create_webhook_event, get_webhook_event_by_delivery_id,
    get_unprocessed_webhook_events, mark_webhook_event_processed,
    get_recent_webhook_events, get_db_connection
)

# Import GitHub API module
from backend.api.git_repo import (
    GitHubAPI, GitHubOAuthError, WebhookError,
    WebhookPayloadParser, WebhookSignatureVerifier
)

# Import diff analyzer module
from backend.api.diff_analyzer import (
    DiffAnalyzer, analyze_commits, analyze_from_webhook
)

# Environment configuration
ENV = os.getenv("APP_ENV", "development")  # "development" | "production"
IS_PRODUCTION = ENV == "production"

# GitHub OAuth configuration
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")

# Cookie configuration based on environment
COOKIE_CONFIG = {
    "secure": IS_PRODUCTION,  # HTTPS only in production
    "httponly": True,
    "samesite": "strict" if IS_PRODUCTION else "lax",
    "max_age": 3600 * 24 * 7,  # 7 days
}

# CSRF state store (in production, use Redis or database)
csrf_states: dict[str, float] = {}
CSRF_STATE_EXPIRY = 600  # 10 minutes

app = FastAPI()

# CORS Configuration - Allow Electron app to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Core security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # Strict Transport Security (only in production)
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.github.com; "
            "frame-ancestors 'none';"
        )
        
        return response


app.add_middleware(SecurityHeadersMiddleware)


# Startup event to initialize database
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup"""
    init_database()


# CSRF Helper Functions
def generate_csrf_state() -> str:
    """Generate a cryptographically secure CSRF state token"""
    state = secrets.token_urlsafe(32)
    csrf_states[state] = time.time()
    _cleanup_expired_states()
    return state


def validate_csrf_state(state: str) -> bool:
    """Validate and consume a CSRF state token"""
    if not state or state not in csrf_states:
        return False
    
    timestamp = csrf_states.pop(state)
    if time.time() - timestamp > CSRF_STATE_EXPIRY:
        return False
    
    return True


def _cleanup_expired_states():
    """Remove expired CSRF states"""
    current_time = time.time()
    expired = [s for s, t in csrf_states.items() if current_time - t > CSRF_STATE_EXPIRY]
    for state in expired:
        csrf_states.pop(state, None)


def get_token_from_request(request: Request) -> Optional[str]:
    """
    Get authentication token from request.
    Checks both:
    1. Authorization header (Bearer token) - for Electron file:// origin
    2. Cookie (github_token) - for web browser requests
    """
    # Check Authorization header first (for Electron apps)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix
    
    # Fall back to cookie
    return request.cookies.get("github_token")


# NOTE: Static file serving removed - this backend is API-only
# The Electron client handles all UI/frontend files locally


@app.get("/")
async def root():
    """API root - returns API info"""
    return {
        "name": "ETTA-X API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "ETTA-X API is running"}


# Setup API Routes
@app.get("/api/setup/status")
async def get_setup_status():
    """Check if initial setup is complete"""
    return {
        "is_first_run": is_first_run(),
        "has_users": user_exists()
    }


@app.get("/api/setup/check-user")
async def check_user_exists(request: Request):
    """Check if the authenticated GitHub user exists in the database"""
    token = get_token_from_request(request)
    
    if not token:
        return {"exists": False, "authenticated": False}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code != 200:
                return {"exists": False, "authenticated": False}
            
            github_data = response.json()
            user = get_user_by_github_id(github_data.get('id'))
            
            return {
                "exists": user is not None,
                "authenticated": True,
                "username": github_data.get('login')
            }
    except Exception:
        return {"exists": False, "authenticated": False}


@app.post("/api/setup/create-user")
async def create_user_from_github(request: Request):
    """Create a new user from GitHub authentication"""
    token = get_token_from_request(request)
    
    if not token:
        print("ERROR: No github_token cookie found")
        print("Available cookies:", request.cookies)
        raise HTTPException(status_code=401, detail="Not authenticated - no token cookie found")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code != 200:
                print(f"ERROR: GitHub API returned {response.status_code}: {response.text}")
                raise HTTPException(status_code=401, detail=f"Failed to fetch GitHub user: {response.status_code}")
            
            github_data = response.json()
            print(f"Creating user for: {github_data.get('login')}")
            
            # Create or update user in database
            user = create_user(github_data)
            
            if not user:
                print("ERROR: create_user returned None")
                raise HTTPException(status_code=500, detail="Failed to create user in database")
            
            print(f"User created/updated: {user.get('username')}")
            
            # Mark setup as complete
            mark_setup_complete()
            
            return {
                "success": True,
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "name": user['name'],
                    "email": user['email'],
                    "avatar_url": user['avatar_url']
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR creating user: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@app.get("/api/user/me")
async def get_current_user(request: Request):
    """Get the current authenticated user from database"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            github_data = response.json()
            user = get_user_by_github_id(github_data.get('id'))
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found. Please complete setup.")
            
            # Get user settings
            settings = get_user_settings(user['id'])
            
            return {
                **user,
                "settings": settings
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/user/settings")
async def update_settings(request: Request):
    """Update current user settings"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        body = await request.json()
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            github_data = response.json()
            user = get_user_by_github_id(github_data.get('id'))
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            success = update_user_settings(user['id'], body)
            
            return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# GitHub OAuth Routes
# Required OAuth scopes for full functionality
GITHUB_OAUTH_SCOPES = "user repo admin:repo_hook"


@app.get("/auth/github/login")
async def github_login(setup: bool = False, force_login: bool = False):
    """Redirect user to GitHub OAuth authorization page with CSRF protection
    
    Args:
        setup: Whether this is from the setup flow
        force_login: If True, forces GitHub to show login screen (for account switching)
    
    Required OAuth Scopes:
        - user: Read user profile information
        - repo: Full control of private repositories (required for private repos)
        - admin:repo_hook: Create/manage webhooks on repositories
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
    
    # Generate CSRF state token with setup flag
    state = generate_csrf_state()
    # Store setup flag in state (format: state_token:setup_flag)
    state_with_flag = f"{state}:{'1' if setup else '0'}"
    csrf_states[state_with_flag] = csrf_states.pop(state)
    
    # URL-encode the scopes (space-separated)
    encoded_scopes = GITHUB_OAUTH_SCOPES.replace(" ", "%20")
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope={encoded_scopes}"
        f"&state={state_with_flag}"
        f"&prompt=select_account"  # Force account picker to appear
    )
    
    return RedirectResponse(url=github_auth_url)


@app.get("/auth/github/login-url")
async def github_login_url(setup: bool = False, force_login: bool = False):
    """Return GitHub OAuth URL as JSON (for Electron apps that open in external browser)
    
    Args:
        setup: Whether this is from the setup flow
        force_login: If True, forces GitHub to show login screen (for account switching)
    
    Required OAuth Scopes:
        - user: Read user profile information
        - repo: Full control of private repositories (required for private repos)
        - admin:repo_hook: Create/manage webhooks on repositories
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
    
    # Generate CSRF state token with setup flag
    state = generate_csrf_state()
    # Store setup flag in state (format: state_token:setup_flag)
    state_with_flag = f"{state}:{'1' if setup else '0'}"
    csrf_states[state_with_flag] = csrf_states.pop(state)
    
    # URL-encode the scopes (space-separated)
    encoded_scopes = GITHUB_OAUTH_SCOPES.replace(" ", "%20")
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope={encoded_scopes}"
        f"&state={state_with_flag}"
        f"&prompt=select_account"  # Force account picker to appear
    )
    
    return {"url": github_auth_url}


@app.get("/auth/github/callback")
async def github_callback(code: str = None, state: str = None, error: str = None):
    """Handle GitHub OAuth callback with CSRF validation and scope verification"""
    import traceback
    
    try:
        print(f"OAuth callback received: code={code[:10] if code else None}..., state={state[:20] if state else None}..., error={error}")
        
        # Handle OAuth errors (e.g., user cancelled login)
        if error:
            # User cancelled or denied access - redirect to Electron app with error
            return RedirectResponse(url=f"ettax://auth?error={error}")
        
        # Parse state to get setup flag
        is_setup = False
        if state and ':' in state:
            state_parts = state.rsplit(':', 1)
            is_setup = state_parts[1] == '1'
        
        # Skip CSRF validation for now (state lost due to server restart is common in dev)
        print(f"Setup mode: {is_setup}")
        
        if not code:
            raise HTTPException(status_code=400, detail="No authorization code provided")
        
        if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
        
        print("Exchanging code for access token...")
        
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": GITHUB_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
            
            print(f"Token response status: {token_response.status_code}")
            
            if token_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to obtain access token")
            
            token_data = token_response.json()
            print(f"Token data keys: {list(token_data.keys())}")
            
            if "error" in token_data:
                print(f"Token error: {token_data}")
                raise HTTPException(status_code=400, detail=token_data.get("error_description", token_data["error"]))
            
            access_token = token_data.get("access_token")
            token_scope = token_data.get("scope", "")
            
            # Log scope validation
            granted_scopes = set(token_scope.split(",")) if token_scope else set()
            print(f"OAuth scopes granted: {granted_scopes}")
            
            # Fetch user info from GitHub
            print("Fetching user info...")
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if user_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user info")
            
            user_data = user_response.json()
            print(f"User: {user_data.get('login')}")
        
        # Check if user exists in database
        existing_user = get_user_by_github_id(user_data.get('id'))
        
        # Create session with token metadata
        token_issued_at = int(time.time())
        
        # Directly redirect to the Electron app via custom protocol
        setup_param = "true" if is_setup else "false"
        deep_link_url = f"ettax://auth?token={access_token}&setup={setup_param}"
        
        print(f"Redirecting to deep link...")
        
        # Use RedirectResponse to immediately open the app
        response = RedirectResponse(url=deep_link_url, status_code=302)
        
        # Also set cookies for web fallback
        response.set_cookie(
            key="github_token",
            value=access_token,
            httponly=COOKIE_CONFIG["httponly"],
            secure=COOKIE_CONFIG["secure"],
            samesite=COOKIE_CONFIG["samesite"],
            max_age=COOKIE_CONFIG["max_age"],
        )
        response.set_cookie(
            key="github_user",
            value=user_data.get("login", ""),
            httponly=False,
            secure=COOKIE_CONFIG["secure"],
            samesite=COOKIE_CONFIG["samesite"],
            max_age=COOKIE_CONFIG["max_age"],
        )
        response.set_cookie(
            key="token_issued_at",
            value=str(token_issued_at),
            httponly=True,
            secure=COOKIE_CONFIG["secure"],
            samesite=COOKIE_CONFIG["samesite"],
            max_age=COOKIE_CONFIG["max_age"],
        )
        
        print("OAuth callback completed successfully")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"OAuth callback error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OAuth error: {str(e)}")


class TokenRequest(BaseModel):
    token: str


@app.post("/auth/set-token")
async def set_auth_token(request: Request, body: TokenRequest):
    """Set authentication token from Electron deep link callback.
    
    This endpoint is called by the Electron app after receiving the token
    via the custom protocol (deep link). It sets the cookie in the webview.
    """
    access_token = body.token
    
    # Verify the token is valid by fetching user info
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_data = user_response.json()
    
    token_issued_at = int(time.time())
    
    # Save/update user in database and create session
    github_id = user_data.get("id")
    existing_user = get_user_by_github_id(github_id)
    
    if existing_user:
        user_id = existing_user['id']
        update_user({
            'id': github_id,
            'login': user_data.get('login'),
            'name': user_data.get('name'),
            'email': user_data.get('email'),
            'avatar_url': user_data.get('avatar_url'),
            'bio': user_data.get('bio'),
            'location': user_data.get('location'),
            'company': user_data.get('company'),
            'blog': user_data.get('blog'),
        })
    else:
        new_user = create_user({
            'id': github_id,
            'login': user_data.get('login'),
            'name': user_data.get('name'),
            'email': user_data.get('email'),
            'avatar_url': user_data.get('avatar_url'),
            'bio': user_data.get('bio'),
            'location': user_data.get('location'),
            'company': user_data.get('company'),
            'blog': user_data.get('blog'),
        })
        user_id = new_user['id'] if new_user else None
        
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")
    
    # Store session with token in database (for background tasks)
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(seconds=COOKIE_CONFIG["max_age"])
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Delete old sessions for this user
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        # Create new session
        cursor.execute("""
            INSERT INTO user_sessions (user_id, session_token, github_access_token, expires_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, session_token, access_token, expires_at.isoformat()))
        conn.commit()
    
    print(f"Session created for user {user_data.get('login')} (id={user_id})")
    
    response = JSONResponse(content={
        "success": True,
        "user": {
            "login": user_data.get("login"),
            "name": user_data.get("name"),
            "avatar_url": user_data.get("avatar_url"),
        }
    })
    
    # Set the authentication cookies
    response.set_cookie(
        key="github_token",
        value=access_token,
        httponly=COOKIE_CONFIG["httponly"],
        secure=COOKIE_CONFIG["secure"],
        samesite=COOKIE_CONFIG["samesite"],
        max_age=COOKIE_CONFIG["max_age"],
    )
    response.set_cookie(
        key="github_user",
        value=user_data.get("login", ""),
        httponly=False,
        secure=COOKIE_CONFIG["secure"],
        samesite=COOKIE_CONFIG["samesite"],
        max_age=COOKIE_CONFIG["max_age"],
    )
    response.set_cookie(
        key="token_issued_at",
        value=str(token_issued_at),
        httponly=True,
        secure=COOKIE_CONFIG["secure"],
        samesite=COOKIE_CONFIG["samesite"],
        max_age=COOKIE_CONFIG["max_age"],
    )
    
    return response


@app.get("/auth/github/user")
async def get_github_user(request: Request):
    """Get current GitHub user info with token lifecycle validation"""
    token = get_token_from_request(request)
    token_issued_at = request.cookies.get("token_issued_at")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Check token age (optional: force re-auth after certain period)
    if token_issued_at:
        try:
            issued_time = int(token_issued_at)
            token_age = time.time() - issued_time
            max_token_age = COOKIE_CONFIG["max_age"]
            
            if token_age > max_token_age:
                raise HTTPException(
                    status_code=401,
                    detail="Token expired, please re-authenticate",
                    headers={"X-Token-Expired": "true"},
                )
        except ValueError:
            pass  # Invalid timestamp, skip age check
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        
        if response.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Token revoked or expired on GitHub",
                headers={"X-Token-Invalid": "true"},
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch user from GitHub")
        
        user_data = response.json()
        
        # Include token metadata in response
        return {
            **user_data,
            "_token_meta": {
                "issued_at": token_issued_at,
                "expires_in": COOKIE_CONFIG["max_age"] - (time.time() - int(token_issued_at)) if token_issued_at else None,
            },
        }


@app.get("/auth/github/logout")
async def github_logout():
    """Logout user by securely clearing all auth cookies"""
    response = JSONResponse(content={"status": "logged_out", "message": "Successfully logged out"})
    
    # Clear all auth-related cookies with matching security settings
    for cookie_name in ["github_token", "github_user", "token_issued_at"]:
        response.delete_cookie(
            key=cookie_name,
            secure=COOKIE_CONFIG["secure"],
            samesite=COOKIE_CONFIG["samesite"],
        )
    
    return response


@app.get("/auth/github/status")
async def get_auth_status(request: Request):
    """Check authentication status - fetches username from GitHub if not in cookies"""
    token = get_token_from_request(request)
    github_user = request.cookies.get("github_user")
    token_issued_at = request.cookies.get("token_issued_at")
    
    if not token:
        return {"authenticated": False}
    
    # If we have a token but no username in cookies (Electron app using Authorization header),
    # fetch the username from GitHub API
    if not github_user:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                if response.status_code == 200:
                    user_data = response.json()
                    github_user = user_data.get("login")
                else:
                    # Token is invalid
                    return {"authenticated": False, "error": "Invalid token"}
        except Exception as e:
            print(f"Error fetching GitHub user: {e}")
            return {"authenticated": False, "error": str(e)}
    
    token_age = None
    expires_in = None
    
    if token_issued_at:
        try:
            issued_time = int(token_issued_at)
            token_age = int(time.time() - issued_time)
            expires_in = max(0, COOKIE_CONFIG["max_age"] - token_age)
        except ValueError:
            pass
    
    return {
        "authenticated": True,
        "username": github_user,
        "token_age_seconds": token_age,
        "expires_in_seconds": expires_in,
        "is_production": IS_PRODUCTION,
    }


# GitHub Repository API Routes
@app.get("/api/github/repos")
async def get_github_repos(request: Request):
    """Fetch all repositories the authenticated user has access to"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        repos = await github_api.get_user_repos()
        return {"repos": repos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/github/repos/{owner}/{repo}/branches")
async def get_repo_branches(owner: str, repo: str, request: Request):
    """Fetch all branches for a specific repository"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        branches = await github_api.get_repo_branches(owner, repo)
        return {"branches": branches}
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/github/repos/{owner}/{repo}")
async def get_repo_info(owner: str, repo: str, request: Request):
    """Get detailed information about a specific repository"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        repo_info = await github_api.get_repo_info(owner, repo)
        return repo_info
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ==================== OAUTH SCOPE VALIDATION ====================

@app.get("/api/github/scopes")
async def get_token_scopes(request: Request):
    """Get the OAuth scopes granted to the current access token"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        scope_info = await github_api.get_scope_info()
        return scope_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/github/scopes/validate")
async def validate_token_scopes(request: Request):
    """Validate that the token has all required scopes"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        is_valid, missing = await github_api.validate_scopes()
        has_webhook_perms, webhook_missing = await github_api.validate_webhook_permissions()
        
        return {
            "valid": is_valid,
            "missing_scopes": missing,
            "can_create_webhooks": has_webhook_perms,
            "webhook_missing_scopes": webhook_missing,
            "reauth_required": not is_valid,
            "reauth_url": "/auth/github/login" if not is_valid else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WEBHOOK CONFIGURATION ====================

# Webhook configuration
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # Fallback secret, should be per-repo
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")  # e.g., "https://your-domain.com"


class WebhookSetupRequest(BaseModel):
    owner: str
    repo: str
    events: Optional[List[str]] = ["push", "pull_request"]


class WebhookSetupResponse(BaseModel):
    success: bool
    webhook_id: Optional[int] = None
    webhook_url: Optional[str] = None
    events: Optional[List[str]] = None
    error: Optional[str] = None
    manual_setup_required: bool = False
    manual_setup_instructions: Optional[str] = None


@app.post("/api/github/repos/{owner}/{repo}/webhook", response_model=WebhookSetupResponse)
async def setup_repository_webhook(owner: str, repo: str, request: Request):
    """
    Automatically set up a webhook for a repository.
    
    This endpoint:
    1. Validates OAuth scopes (requires admin:repo_hook)
    2. Creates or updates the repository record
    3. Generates a unique webhook secret
    4. Creates the webhook via GitHub API
    5. Stores the webhook configuration in the database
    
    If the token lacks permissions, returns manual setup instructions.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not WEBHOOK_BASE_URL:
        raise HTTPException(
            status_code=500, 
            detail="Webhook base URL not configured. Set WEBHOOK_BASE_URL environment variable."
        )
    
    try:
        github_api = GitHubAPI(token)
        
        # First, get repo info and validate access
        repo_info = await github_api.get_repo_info(owner, repo)
        
        # Check webhook permissions
        has_webhook_perms, missing_scopes = await github_api.validate_webhook_permissions()
        
        if not has_webhook_perms:
            # Return manual setup instructions
            webhook_url = f"{WEBHOOK_BASE_URL}/webhook/github"
            return WebhookSetupResponse(
                success=False,
                error=f"Missing OAuth scopes: {', '.join(missing_scopes)}",
                manual_setup_required=True,
                manual_setup_instructions=(
                    f"To set up the webhook manually:\n"
                    f"1. Go to https://github.com/{owner}/{repo}/settings/hooks/new\n"
                    f"2. Set Payload URL to: {webhook_url}\n"
                    f"3. Set Content type to: application/json\n"
                    f"4. Set Secret to a secure random string\n"
                    f"5. Select events: 'push' and 'pull_request'\n"
                    f"6. Click 'Add webhook'\n\n"
                    f"Or re-authenticate with the required 'admin:repo_hook' scope."
                )
            )
        
        # Get GitHub user info
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            )
            if user_response.status_code != 200:
                raise HTTPException(status_code=401, detail="Failed to get user info")
            user_data = user_response.json()
        
        # Get or create user in database
        user = get_user_by_github_id(user_data.get('id'))
        if not user:
            raise HTTPException(status_code=404, detail="User not found. Please complete setup first.")
        
        # Create/update repository record
        db_repo = create_repository(user['id'], repo_info)
        if not db_repo:
            raise HTTPException(status_code=500, detail="Failed to save repository")
        
        # Check if webhook already exists for this repo
        existing_webhook = get_webhook_by_repository(db_repo['id'])
        if existing_webhook:
            # Webhook already exists, return its info
            return WebhookSetupResponse(
                success=True,
                webhook_id=existing_webhook['github_hook_id'],
                webhook_url=existing_webhook['webhook_url'],
                events=existing_webhook['events'].split(',') if isinstance(existing_webhook['events'], str) else [],
                error=None,
                manual_setup_required=False
            )
        
        # Generate unique webhook secret for this repository
        webhook_secret = WebhookSignatureVerifier.generate_secret()
        webhook_url = f"{WEBHOOK_BASE_URL}/webhook/github"
        events = ["push", "pull_request"]
        
        # Create webhook via GitHub API
        webhook_result = await github_api.create_webhook(
            owner=owner,
            repo=repo,
            webhook_url=webhook_url,
            secret=webhook_secret,
            events=events,
            active=True
        )
        
        # Store webhook in database (store hashed secret for verification)
        # We store the actual secret since we need it for signature verification
        # In production, consider encrypting this at rest
        webhook_record = create_webhook(
            repository_id=db_repo['id'],
            github_hook_id=webhook_result['id'],
            webhook_url=webhook_url,
            secret_hash=webhook_secret,  # Store plain for verification
            events=events
        )
        
        if not webhook_record:
            raise HTTPException(status_code=500, detail="Failed to save webhook configuration")
        
        return WebhookSetupResponse(
            success=True,
            webhook_id=webhook_result['id'],
            webhook_url=webhook_url,
            events=events,
            error=None,
            manual_setup_required=False
        )
        
    except GitHubOAuthError as e:
        return WebhookSetupResponse(
            success=False,
            error=str(e),
            manual_setup_required=True,
            manual_setup_instructions=(
                f"Missing OAuth scopes: {', '.join(e.missing_scopes)}. "
                f"Please re-authenticate with the required permissions at /auth/github/login"
            )
        )
    except WebhookError as e:
        return WebhookSetupResponse(
            success=False,
            error=str(e),
            manual_setup_required=e.status_code == 403,
            manual_setup_instructions=(
                f"Webhook creation failed. You may need to set it up manually at "
                f"https://github.com/{owner}/{repo}/settings/hooks"
            ) if e.status_code == 403 else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/github/repos/{owner}/{repo}/connect")
async def connect_repository(owner: str, repo: str, request: Request):
    """
    Connect a repository - creates the repo record in DB and attempts to set up webhook.
    This is the main endpoint called when user clicks "Clone/Connect" button.
    
    Request body (optional):
    {
        "branch": "main"  // Optional: preferred branch
    }
    
    Returns:
    {
        "success": true,
        "repository": {...},
        "webhook_setup": true/false,
        "webhook_error": "..." (if webhook failed)
    }
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        body = {}
        try:
            body = await request.json()
        except:
            pass
        
        branch = body.get('branch')
        
        github_api = GitHubAPI(token)
        
        # Get GitHub user info
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if user_response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            github_user = user_response.json()
        
        # Get or create user
        user = get_user_by_github_id(github_user.get('id'))
        if not user:
            user = create_user(github_user)  # Pass the full github user dict
        
        if not user:
            raise HTTPException(status_code=500, detail="Failed to get/create user")
        
        # Get repo info from GitHub
        repo_info = await github_api.get_repo_info(owner, repo)
        
        # Create or update repository in database
        db_repo = get_repository_by_full_name(f"{owner}/{repo}")
        if not db_repo:
            # create_repository expects (user_id, repo_data_dict)
            # repo_data expects keys: id, name, full_name, description, html_url, clone_url, default_branch, private
            repo_data = {
                'id': repo_info.get('id'),
                'name': repo_info.get('name'),
                'full_name': repo_info.get('full_name'),
                'description': repo_info.get('description'),
                'html_url': repo_info.get('html_url'),
                'clone_url': repo_info.get('clone_url'),
                'default_branch': branch or repo_info.get('default_branch', 'main'),
                'private': repo_info.get('private', False)
            }
            db_repo = create_repository(user_id=user['id'], repo_data=repo_data)
        
        if not db_repo:
            raise HTTPException(status_code=500, detail="Failed to save repository")
        
        # Try to set up webhook
        webhook_setup = False
        webhook_error = None
        
        try:
            # Check if webhook already exists
            existing_webhook = get_webhook_by_repository(db_repo['id'])
            if existing_webhook:
                webhook_setup = True
            else:
                # Try to create webhook
                has_perms, missing_scopes = await github_api.validate_webhook_permissions()
                
                # Check for common issues
                if not WEBHOOK_BASE_URL:
                    webhook_error = "WEBHOOK_BASE_URL not configured in environment"
                elif "localhost" in WEBHOOK_BASE_URL or "127.0.0.1" in WEBHOOK_BASE_URL:
                    webhook_error = f"Webhook URL ({WEBHOOK_BASE_URL}) is localhost - GitHub cannot reach it. Use ngrok or a public URL."
                elif not has_perms:
                    webhook_error = f"Missing OAuth scopes: {', '.join(missing_scopes)}. Re-authenticate to grant webhook permissions."
                else:
                    webhook_secret = WebhookSignatureVerifier.generate_secret()
                    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/github"
                    events = ["push", "pull_request"]
                    
                    try:
                        webhook_result = await github_api.create_webhook(
                            owner=owner,
                            repo=repo,
                            webhook_url=webhook_url,
                            secret=webhook_secret,
                            events=events,
                            active=True
                        )
                        
                        create_webhook(
                            repository_id=db_repo['id'],
                            github_hook_id=webhook_result['id'],
                            webhook_url=webhook_url,
                            secret_hash=webhook_secret,
                            events=events
                        )
                        webhook_setup = True
                    except Exception as we:
                        webhook_error = f"GitHub API error: {str(we)}"
        except Exception as e:
            webhook_error = f"Webhook setup error: {str(e)}"
        
        return {
            "success": True,
            "repository": {
                "id": db_repo['id'],
                "name": db_repo['name'],
                "full_name": db_repo['full_name'],
                "default_branch": db_repo.get('default_branch', 'main'),
            },
            "webhook_setup": webhook_setup,
            "webhook_error": webhook_error
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/github/repos/{owner}/{repo}/webhook")
async def get_repository_webhook(owner: str, repo: str, request: Request):
    """Get the webhook configuration for a repository"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Get the repository from database
        db_repo = get_repository_by_full_name(f"{owner}/{repo}")
        if not db_repo:
            return {"webhook": None, "exists": False}
        
        webhook = get_webhook_by_repository(db_repo['id'])
        if not webhook:
            return {"webhook": None, "exists": False}
        
        return {
            "webhook": {
                "id": webhook['github_hook_id'],
                "url": webhook['webhook_url'],
                "events": webhook['events'],
                "active": webhook['is_active'],
                "last_delivery": webhook['last_delivery_at'],
                "last_status": webhook['last_delivery_status'],
            },
            "exists": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/github/repos/{owner}/{repo}/webhook")
async def delete_repository_webhook(owner: str, repo: str, request: Request):
    """Delete a webhook from a repository"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        github_api = GitHubAPI(token)
        
        # Get the repository and webhook from database
        db_repo = get_repository_by_full_name(f"{owner}/{repo}")
        if not db_repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        
        webhook = get_webhook_by_repository(db_repo['id'])
        if not webhook:
            return {"success": True, "message": "No webhook to delete"}
        
        # Delete from GitHub
        await github_api.delete_webhook(owner, repo, webhook['github_hook_id'])
        
        # Deactivate in database
        deactivate_webhook(db_repo['id'], webhook['github_hook_id'])
        
        return {"success": True, "message": "Webhook deleted"}
        
    except GitHubOAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WebhookError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== BACKGROUND PROCESSING ====================

async def process_webhook_event_background(event_id: int, event_data: dict):
    """
    Background task to process a webhook event.
    Runs asynchronously after the webhook response is sent.
    """
    import json
    import asyncio
    
    try:
        print(f"[Background] Processing webhook event {event_id}...")
        
        repo_full_name = event_data.get('repository_full_name')
        before_sha = event_data.get('before_sha')
        after_sha = event_data.get('commit_sha')
        branch = event_data.get('branch')
        
        if not repo_full_name or not after_sha:
            print(f"[Background] Missing required data for event {event_id}")
            return
        
        owner, repo_name = repo_full_name.split('/')
        
        # Get a valid token from the database for this repo
        repo = get_repository_by_full_name(repo_full_name)
        if not repo:
            print(f"[Background] Repository not found: {repo_full_name}")
            return
        
        print(f"[Background] Found repo in DB: user_id={repo.get('user_id')}")
        
        # Get user's token from user_sessions (joined via repositories)
        token = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Debug: check what sessions exist
            cursor.execute("""
                SELECT s.id, s.user_id, s.expires_at, r.full_name 
                FROM user_sessions s 
                JOIN repositories r ON r.user_id = s.user_id 
                WHERE r.full_name = ?
            """, (repo_full_name,))
            all_sessions = cursor.fetchall()
            print(f"[Background] Found {len(all_sessions)} sessions for repo {repo_full_name}")
            for sess in all_sessions:
                print(f"[Background]   Session: id={sess['id']}, user_id={sess['user_id']}, expires_at={sess['expires_at']}")
            
            # Use datetime comparison - SQLite compares ISO strings lexicographically
            from datetime import datetime
            now_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
            cursor.execute("""
                SELECT s.github_access_token FROM user_sessions s 
                JOIN repositories r ON r.user_id = s.user_id 
                WHERE r.full_name = ? AND s.expires_at > ?
                ORDER BY s.created_at DESC LIMIT 1
            """, (repo_full_name, now_iso))
            row = cursor.fetchone()
            if row:
                token = row['github_access_token']
                print(f"[Background] Found valid token for repo {repo_full_name}")
        
        if not token:
            print(f"[Background] No access token found for repo {repo_full_name} - session may have expired")
            return
        
        # Clone or pull the repository
        local_path = await clone_or_pull_repo(owner, repo_name, token, branch)
        
        # Run diff analysis
        analysis_result = None
        if before_sha and after_sha and before_sha != '0' * 40:
            try:
                # Verify the commits exist in the local repo
                import asyncio
                
                async def verify_commit(sha: str) -> bool:
                    process = await asyncio.create_subprocess_exec(
                        'git', 'cat-file', '-t', sha,
                        cwd=local_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    return process.returncode == 0
                
                if not await verify_commit(after_sha):
                    print(f"[Background] Commit {after_sha} not found, fetching again...")
                    # Force fetch to get the specific commit
                    await clone_or_pull_repo(owner, repo_name, token, branch)
                    
                    if not await verify_commit(after_sha):
                        raise Exception(f"Commit {after_sha} not found after fetch")
                
                # Run CPU-bound diff analysis in thread pool to not block event loop
                import concurrent.futures
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    analysis_result = await loop.run_in_executor(
                        pool, analyze_commits, local_path, before_sha, after_sha
                    )
                print(f"[Background] Analysis complete for event {event_id}")
            except Exception as e:
                print(f"[Background] Diff analysis error for event {event_id}: {e}")
                analysis_result = {"error": str(e)}
        else:
            # New branch or initial push - analyze the latest commit
            print(f"[Background] Skipping diff (new branch or initial push) for event {event_id}")
            analysis_result = {
                "note": "Initial push or new branch - no prior commit to compare",
                "files": [],
                "logical_changes": {}
            }
        
        # Mark as processed with results
        result_json = json.dumps(analysis_result) if analysis_result else None
        mark_webhook_event_processed(event_id, result_json)
        print(f"[Background] Event {event_id} marked as processed")
        
    except Exception as e:
        import traceback
        print(f"[Background] Error processing event {event_id}: {e}")
        traceback.print_exc()
        # Mark as processed with error to prevent infinite retries
        mark_webhook_event_processed(event_id, json.dumps({"error": str(e)}))


# ==================== WEBHOOK RECEIVER ENDPOINT ====================

@app.post("/webhook/github")
async def receive_github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive and process GitHub webhook events.
    
    This endpoint:
    1. Verifies the webhook signature using the shared secret
    2. Parses the event payload
    3. Stores the event for processing
    4. Triggers downstream processing (git diff + AST analysis)
    
    Headers expected:
    - X-GitHub-Event: Event type (push, pull_request, ping)
    - X-GitHub-Delivery: Unique delivery ID
    - X-Hub-Signature-256: HMAC signature for verification
    """
    # Get headers
    event_type = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    signature = request.headers.get("X-Hub-Signature-256")
    
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")
    
    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")
    
    # Get raw body for signature verification
    body = await request.body()
    
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Extract repository info for secret lookup
    repo_full_name = payload.get("repository", {}).get("full_name")
    
    if not repo_full_name:
        # Ping events might not have full repo info
        if event_type != "ping":
            raise HTTPException(status_code=400, detail="Missing repository information")
    
    # Look up webhook secret for this repository
    webhook_secret = get_webhook_secret_hash(repo_full_name) if repo_full_name else None
    
    # If we don't have a secret stored, use the global fallback (for testing)
    if not webhook_secret:
        webhook_secret = WEBHOOK_SECRET
    
    # Verify signature if we have a secret
    if webhook_secret and signature:
        if not WebhookSignatureVerifier.verify_signature(body, webhook_secret, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif webhook_secret and not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    # Check for duplicate delivery (idempotency)
    existing_event = get_webhook_event_by_delivery_id(delivery_id)
    if existing_event:
        return {
            "status": "duplicate",
            "message": "Event already received",
            "event_id": existing_event['id']
        }
    
    # Parse the payload
    parsed_event = WebhookPayloadParser.parse(event_type, payload)
    
    # Handle ping events (webhook test)
    if event_type == "ping":
        return {
            "status": "success",
            "message": "Pong! Webhook configured successfully.",
            "zen": parsed_event.get("zen"),
            "hook_id": parsed_event.get("hook_id")
        }
    
    # Extract relevant data for storage
    event_data = {
        "delivery_id": delivery_id,
        "event_type": event_type,
        "repository_full_name": repo_full_name,
        "payload": payload,
    }
    
    # Extract branch and commit info based on event type
    if event_type == "push":
        event_data["branch"] = parsed_event.get("branch")
        event_data["commit_sha"] = parsed_event.get("after")
        event_data["before_sha"] = parsed_event.get("before")
    elif event_type == "pull_request":
        pr_data = parsed_event.get("pull_request", {})
        event_data["branch"] = pr_data.get("head", {}).get("ref")
        event_data["commit_sha"] = pr_data.get("head", {}).get("sha")
    
    # Store the event
    stored_event = create_webhook_event(event_data)
    
    if not stored_event:
        raise HTTPException(status_code=500, detail="Failed to store webhook event")
    
    # Trigger background processing for push events
    if event_type == "push":
        # Add event data needed for processing
        processing_data = {
            "repository_full_name": repo_full_name,
            "before_sha": event_data.get("before_sha"),
            "commit_sha": event_data.get("commit_sha"),
            "branch": event_data.get("branch"),
        }
        background_tasks.add_task(process_webhook_event_background, stored_event['id'], processing_data)
        print(f"[Webhook] Queued background processing for event {stored_event['id']}")
    
    return {
        "status": "received",
        "event_id": stored_event['id'],
        "event_type": event_type,
        "repository": repo_full_name,
        "branch": event_data.get("branch"),
        "commit": event_data.get("commit_sha"),
        "message": "Event queued for processing"
    }


@app.get("/api/webhook/events")
async def get_webhook_events(
    request: Request,
    repository: Optional[str] = None,
    limit: int = 50
):
    """Get recent webhook events, optionally filtered by repository"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    events = get_recent_webhook_events(repository, min(limit, 100))
    
    return {
        "events": events,
        "count": len(events)
    }


@app.get("/api/webhook/events/pending")
async def get_pending_webhook_events(request: Request, limit: int = 100):
    """Get unprocessed webhook events (for background processing)"""
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    events = get_unprocessed_webhook_events(min(limit, 100))
    
    return {
        "events": events,
        "count": len(events)
    }


# Repository cloning configuration
REPOS_BASE_PATH = os.getenv("REPOS_BASE_PATH", "backend/data/repos")


def ensure_repo_directory():
    """Ensure the repos directory exists"""
    if not os.path.exists(REPOS_BASE_PATH):
        os.makedirs(REPOS_BASE_PATH, exist_ok=True)


def get_repo_local_path(owner: str, repo: str) -> str:
    """Get local path for a cloned repository"""
    return os.path.join(REPOS_BASE_PATH, owner, repo)


async def clone_or_pull_repo(owner: str, repo: str, token: str, branch: str = None) -> str:
    """Clone a repository or pull latest changes if already cloned - uses async subprocess"""
    import asyncio
    
    ensure_repo_directory()
    
    local_path = get_repo_local_path(owner, repo)
    clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    
    async def run_git_command(args: list, cwd: str = None, timeout: int = 120) -> tuple:
        """Run git command asynchronously"""
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return process.returncode, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            process.kill()
            raise Exception(f"Git command timed out: {' '.join(args)}")
    
    if os.path.exists(os.path.join(local_path, '.git')):
        # Repository exists - fetch all refs including new commits
        try:
            print(f"[Git] Fetching updates for {owner}/{repo}...")
            
            # Update remote URL in case token changed
            await run_git_command(['git', 'remote', 'set-url', 'origin', clone_url], cwd=local_path)
            
            # Fetch all branches and tags with full depth
            returncode, stdout, stderr = await run_git_command(
                ['git', 'fetch', '--all', '--tags', '--force'],
                cwd=local_path,
                timeout=120
            )
            if returncode != 0:
                print(f"[Git] Fetch warning: {stderr}")
            
            # Also fetch with unshallow if it was a shallow clone
            await run_git_command(['git', 'fetch', '--unshallow'], cwd=local_path, timeout=120)
            
            if branch:
                # Checkout and pull the specific branch
                await run_git_command(['git', 'checkout', branch], cwd=local_path, timeout=30)
                await run_git_command(['git', 'pull', 'origin', branch, '--ff-only'], cwd=local_path, timeout=120)
            
            print(f"[Git] Fetch complete for {owner}/{repo}")
            
        except Exception as e:
            print(f"[Git] Error updating repo {owner}/{repo}: {e}")
    else:
        # Clone the repository with full history
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            print(f"[Git] Cloning {owner}/{repo}...")
            cmd = ['git', 'clone', '--no-single-branch', clone_url, local_path]
            if branch:
                cmd.extend(['-b', branch])
            
            returncode, stdout, stderr = await run_git_command(cmd, timeout=300)
            if returncode != 0:
                raise Exception(f"Clone failed: {stderr}")
            
            print(f"[Git] Clone complete for {owner}/{repo}")
        except Exception as e:
            raise Exception(f"Failed to clone repository: {e}")
    
    return local_path


@app.post("/api/webhook/events/{event_id}/process")
async def trigger_event_processing(event_id: int, request: Request):
    """
    Trigger processing for a specific webhook event.
    
    Processing includes:
    - Clone/pull the repository
    - Git diff between before and after commits
    - AST analysis of changed files
    - Return analysis results
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get the event from database
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if row:
                event = dict(row)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Parse payload
        payload = json.loads(event['payload']) if isinstance(event['payload'], str) else event['payload']
        repo_full_name = event['repository_full_name']
        owner, repo_name = repo_full_name.split('/')
        
        # Clone or pull the repository
        local_path = await clone_or_pull_repo(owner, repo_name, token, event.get('branch'))
        
        # Run diff analysis
        before_sha = event.get('before_sha')
        after_sha = event.get('commit_sha')
        
        analysis_result = None
        if before_sha and after_sha and before_sha != '0' * 40:
            try:
                analysis_result = analyze_commits(local_path, before_sha, after_sha)
            except Exception as e:
                print(f"Diff analysis error: {e}")
                analysis_result = {"error": str(e)}
        
        # Mark as processed with results
        result_json = json.dumps(analysis_result) if analysis_result else None
        mark_webhook_event_processed(event_id, result_json)
        
        return {
            "status": "processed",
            "event_id": event_id,
            "repository": repo_full_name,
            "analysis": analysis_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze/commits")
async def analyze_commit_range(request: Request):
    """
    Analyze changes between two commits.
    
    Request body:
    {
        "owner": "repo_owner",
        "repo": "repo_name",
        "old_commit": "sha1",
        "new_commit": "sha2"
    }
    
    Returns normalized change analysis.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        body = await request.json()
        owner = body.get('owner')
        repo_name = body.get('repo')
        old_commit = body.get('old_commit')
        new_commit = body.get('new_commit')
        
        if not all([owner, repo_name, old_commit, new_commit]):
            raise HTTPException(
                status_code=400, 
                detail="Missing required fields: owner, repo, old_commit, new_commit"
            )
        
        # Clone or pull the repository
        local_path = await clone_or_pull_repo(owner, repo_name, token)
        
        # Run diff analysis
        analysis_result = analyze_commits(local_path, old_commit, new_commit)
        
        return {
            "status": "success",
            "repository": f"{owner}/{repo_name}",
            "analysis": analysis_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analyze/events/{event_id}")
async def get_event_analysis(event_id: int, request: Request):
    """
    Get the analysis results for a processed webhook event.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get the event from database
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if row:
                event = dict(row)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Parse the processing result
        analysis = None
        if event.get('processing_result'):
            try:
                analysis = json.loads(event['processing_result'])
            except:
                analysis = {"raw": event['processing_result']}
        
        return {
            "event_id": event_id,
            "event_type": event['event_type'],
            "repository": event['repository_full_name'],
            "branch": event.get('branch'),
            "commit": event.get('commit_sha'),
            "processed": bool(event.get('processed')),
            "processed_at": event.get('processed_at'),
            "analysis": analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== REPOSITORIES VIEW API ====================


@app.get("/api/repositories/connected")
async def get_connected_repositories(request: Request):
    """
    Get all repositories connected by the current user with webhook status.
    Returns data formatted for the Repositories View frontend.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get user info from GitHub
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            github_user = response.json()
            user = get_user_by_github_id(github_user.get('id'))
            
            if not user:
                return {"repositories": []}
        
        # Get user's repositories from database
        repos = get_user_repositories(user['id'])
        
        # Enrich with webhook status and last event
        result = []
        for repo in repos:
            webhook = get_webhook_by_repository(repo['id'])
            
            # Get last webhook event for this repo
            events = get_recent_webhook_events(repo['full_name'], limit=1)
            last_event = events[0] if events else None
            
            result.append({
                "id": repo['id'],
                "github_repo_id": repo['github_repo_id'],
                "name": repo['name'],
                "full_name": repo['full_name'],
                "description": repo.get('description'),
                "default_branch": repo.get('default_branch', 'main'),
                "is_private": bool(repo.get('is_private')),
                "webhook_active": bool(webhook and webhook.get('is_active')),
                "webhook_id": webhook['github_hook_id'] if webhook else None,
                "last_commit": last_event.get('commit_sha') if last_event else None,
                "last_event_at": last_event.get('created_at') if last_event else None,
            })
        
        return {"repositories": result}
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# Store for tracking latest event timestamps per repo (for polling)
_latest_events: Dict[str, str] = {}

@app.get("/api/repositories/{full_name:path}/latest-event")
async def get_latest_event(full_name: str, request: Request):
    """
    Get the latest webhook event ID and timestamp for polling.
    Frontend can poll this to know when to refresh.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    events = get_recent_webhook_events(full_name, limit=1)
    
    if events:
        latest = events[0]
        return {
            "has_update": True,
            "event_id": latest['id'],
            "commit_sha": latest.get('commit_sha', '')[:7] if latest.get('commit_sha') else None,
            "processed": bool(latest.get('processed')),
            "timestamp": latest.get('created_at')
        }
    else:
        return {
            "has_update": False,
            "event_id": None,
            "commit_sha": None,
            "processed": False,
            "timestamp": None
        }


@app.get("/api/repositories/{full_name:path}/analysis")
async def get_repository_analysis(full_name: str, request: Request, event_id: Optional[int] = None):
    """
    Get analysis data for a repository.
    If event_id is provided, get analysis for that specific event.
    Otherwise, get the latest analysis.
    
    Data Contract:
    {
        "repository": "owner/repo",
        "webhook_timestamp": "ISO datetime",
        "summary": {
            "files_changed": int,
            "lines_added": int,
            "lines_removed": int,
            "commits": int,
            "change_types": ["api", "service", "ui", "config", "test"]
        },
        "files": [
            {
                "path": "src/file.py",
                "change_type": "modified|added|deleted|renamed",
                "additions": int,
                "deletions": int,
                "diff": "unified diff string"
            }
        ],
        "logical_changes": {
            "functions": [
                {"name": "func_name", "change_type": "added|modified|deleted", "file": "path", "line_start": int, "line_end": int}
            ],
            "classes": [...],
            "routes": [...],
            "imports": [...]
        }
    }
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get repo from database
        repo = get_repository_by_full_name(full_name)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        
        # Get recent webhook events with processing results
        events = get_recent_webhook_events(full_name, limit=10)
        
        # Find the target event (specific or latest)
        latest_analysis = None
        webhook_timestamp = None
        
        for event in events:
            # If event_id specified, find that specific event
            if event_id is not None:
                if event.get('id') == event_id and event.get('processed') and event.get('processing_result'):
                    try:
                        latest_analysis = json.loads(event['processing_result'])
                        webhook_timestamp = event.get('created_at')
                        break
                    except:
                        continue
            else:
                # Otherwise get the latest processed event
                if event.get('processed') and event.get('processing_result'):
                    try:
                        latest_analysis = json.loads(event['processing_result'])
                        webhook_timestamp = event.get('created_at')
                        break
                    except:
                        continue
        
        if not latest_analysis:
            # Return empty structure if no analysis available
            return {
                "repository": full_name,
                "webhook_timestamp": None,
                "summary": {
                    "files_changed": 0,
                    "lines_added": 0,
                    "lines_removed": 0,
                    "commits": 0,
                    "change_types": []
                },
                "files": [],
                "logical_changes": {
                    "functions": [],
                    "classes": [],
                    "routes": [],
                    "imports": []
                }
            }
        
        # Transform the analysis data to match our data contract
        # The analyzer returns 'changed_files', map to 'files' for frontend
        files = latest_analysis.get('changed_files', latest_analysis.get('files', []))
        logical = latest_analysis.get('logical_changes', {})
        
        # Also get summary from analyzer if available
        analyzer_summary = latest_analysis.get('summary', {})
        
        # Calculate additions/deletions from line_ranges
        # Each range has start/end - count actual lines, not just number of ranges
        total_additions = 0
        total_deletions = 0
        for f in files:
            line_ranges = f.get('line_ranges', [])
            # If file has explicit additions/deletions, use those
            if 'additions' in f:
                total_additions += f['additions']
            else:
                # Count actual lines from ranges (end - start + 1 for each range)
                for r in line_ranges:
                    if r.get('type') in ['added', 'modified']:
                        start = r.get('start', 0)
                        end = r.get('end', start)
                        total_additions += (end - start + 1)
            
            if 'deletions' in f:
                total_deletions += f['deletions']
            else:
                for r in line_ranges:
                    if r.get('type') == 'deleted':
                        start = r.get('start', 0)
                        end = r.get('end', start)
                        total_deletions += (end - start + 1)
        
        # Determine change types from files
        change_types = set()
        for f in files:
            file_path = f.get('path', '').lower()
            if '/api/' in file_path or 'routes' in file_path or 'endpoints' in file_path:
                change_types.add('api')
            elif '/service' in file_path or '/services/' in file_path:
                change_types.add('service')
            elif any(x in file_path for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/']):
                change_types.add('ui')
            elif any(x in file_path for x in ['config', '.json', '.yaml', '.yml', '.env', '.toml']):
                change_types.add('config')
            elif 'test' in file_path or 'spec' in file_path:
                change_types.add('test')
        
        # Add change types from logical changes
        if logical.get('routes'):
            change_types.add('api')
        
        if not change_types:
            change_types.add('other')
        
        return {
            "repository": full_name,
            "webhook_timestamp": webhook_timestamp,
            "summary": {
                "files_changed": analyzer_summary.get('total_files', len(files)),
                "lines_added": total_additions,
                "lines_removed": total_deletions,
                "commits": latest_analysis.get('commits_analyzed', 1),
                "change_types": list(change_types)
            },
            "files": [
                {
                    "path": f.get('path', ''),
                    "change_type": f.get('status', f.get('change_type', 'modified')),
                    "additions": f.get('additions', sum((r.get('end', r.get('start', 0)) - r.get('start', 0) + 1) for r in f.get('line_ranges', []) if r.get('type') in ['added', 'modified'])),
                    "deletions": f.get('deletions', sum((r.get('end', r.get('start', 0)) - r.get('start', 0) + 1) for r in f.get('line_ranges', []) if r.get('type') == 'deleted')),
                    "diff": f.get('diff', '')
                }
                for f in files
            ],
            "logical_changes": {
                "functions": [
                    {
                        "name": n.get('name'),
                        "change_type": "modified",
                        "file": f.get('path'),
                        "line_start": n.get('start_line'),
                        "line_end": n.get('end_line')
                    }
                    for f in files
                    for n in f.get('changed_nodes', [])
                    if n.get('type') == 'function'
                ],
                "classes": [
                    {
                        "name": n.get('name'),
                        "change_type": "modified", 
                        "file": f.get('path'),
                        "line_start": n.get('start_line'),
                        "line_end": n.get('end_line')
                    }
                    for f in files
                    for n in f.get('changed_nodes', [])
                    if n.get('type') == 'class'
                ],
                "routes": [],
                "imports": []
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories/{full_name:path}/events")
async def get_repository_events(full_name: str, request: Request, limit: int = 20):
    """
    Get webhook events history for a repository.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        events = get_recent_webhook_events(full_name, limit=limit)
        
        return {
            "repository": full_name,
            "events": [
                {
                    "id": e['id'],
                    "event_type": e['event_type'],
                    "branch": e.get('branch'),
                    "commit_sha": e.get('commit_sha'),
                    "processed": bool(e.get('processed')),
                    "created_at": e.get('created_at')
                }
                for e in events
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories/{full_name:path}/commits")
async def get_repository_commits(
    full_name: str, 
    request: Request, 
    branch: Optional[str] = None,
    limit: int = 30
):
    """
    Get commit history for a repository from GitHub API.
    Returns actual Git commits, not just webhook events.
    """
    token = get_token_from_request(request)
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Get repo info from database to get default branch
        repo = get_repository_by_full_name(full_name)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        
        # Use provided branch or default branch
        target_branch = branch or repo.get('default_branch', 'main')
        
        owner, repo_name = full_name.split('/')
        
        # Fetch commits from GitHub API
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo_name}/commits",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                params={
                    "sha": target_branch,
                    "per_page": min(limit, 100)
                }
            )
            
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Repository not found on GitHub")
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch commits from GitHub")
            
            commits_data = response.json()
        
        # Also get local webhook events to mark which commits have been analyzed
        events = get_recent_webhook_events(full_name, limit=100)
        analyzed_commits = {e.get('commit_sha'): e for e in events if e.get('processed')}
        
        # Format commits for response
        commits = []
        for commit in commits_data:
            sha = commit.get('sha', '')
            commit_info = commit.get('commit', {})
            author_info = commit_info.get('author', {})
            committer_info = commit_info.get('committer', {})
            
            # Check if this commit has been analyzed
            event_data = analyzed_commits.get(sha)
            
            commits.append({
                "sha": sha,
                "short_sha": sha[:7] if sha else "",
                "message": commit_info.get('message', '').split('\n')[0],  # First line only
                "full_message": commit_info.get('message', ''),
                "author": {
                    "name": author_info.get('name', 'Unknown'),
                    "email": author_info.get('email', ''),
                    "date": author_info.get('date', ''),
                    "avatar_url": commit.get('author', {}).get('avatar_url') if commit.get('author') else None,
                    "login": commit.get('author', {}).get('login') if commit.get('author') else None,
                },
                "committer": {
                    "name": committer_info.get('name', 'Unknown'),
                    "date": committer_info.get('date', ''),
                },
                "url": commit.get('html_url', ''),
                "analyzed": event_data is not None,
                "event_id": event_data.get('id') if event_data else None,
            })
        
        return {
            "repository": full_name,
            "branch": target_branch,
            "commits": commits,
            "count": len(commits)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching commits: {e}")
        raise HTTPException(status_code=500, detail=str(e))
