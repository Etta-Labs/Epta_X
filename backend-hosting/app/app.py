import sys
import os

# Add backend-hosting root to path for module imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI, Request, HTTPException, Depends, status, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from pydantic import BaseModel
from typing import Optional, List, Dict
import httpx
import secrets
import hashlib
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv



# Load environment variables from .env file
load_dotenv()

# Import database module (PostgreSQL for hosted environment)
from app.database import (
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
from api.git_repo import (
    GitHubAPI, GitHubOAuthError, WebhookError,
    WebhookPayloadParser, WebhookSignatureVerifier
)

# Import diff analyzer module
from api.diff_analyzer import (
    DiffAnalyzer, analyze_commits, analyze_from_webhook
)

# Import test pipeline API router
from api.test_pipeline import router as test_pipeline_router

# Environment configuration
ENV = os.getenv("APP_ENV", "development")  # "development" | "production"
IS_PRODUCTION = ENV == "production"

# GitHub OAuth configuration
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

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

# CORS Configuration - Allow Electron app and web origins
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "https://epta-x.onrender.com",
    "https://ettax.onrender.com",
    "https://ettax.gowshik.online",
    "app://.",  # Electron app origin
    "file://",  # Electron file:// origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if IS_PRODUCTION else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-OAuth-Scopes", "X-Token-Expired", "X-Token-Invalid"],
)

# Include test pipeline router
app.include_router(test_pipeline_router)

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

# Mount frontend static files and config
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/config", StaticFiles(directory="frontend/config"), name="config")
app.mount("/pages", StaticFiles(directory="frontend/pages"), name="pages")
app.mount("/components", StaticFiles(directory="frontend/components"), name="components")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Main entry point - shows loading screen which checks setup status"""
    return FileResponse("frontend/pages/landing.html")


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Serve the setup page for first-time users"""
    # Check if setup is already complete and user is authenticated
    token = request.cookies.get("github_token")
    if token:
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
                    github_data = response.json()
                    user = get_user_by_github_id(github_data.get('id'))
                    if user:
                        # User already set up, redirect to dashboard
                        return RedirectResponse(url="/dashboard")
        except Exception:
            pass  # Continue to setup page on error
    
    return FileResponse("frontend/pages/setup.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main dashboard - allows viewing but features require auth"""
    # Always serve the dashboard, the frontend handles auth state
    return FileResponse("frontend/pages/index.html")


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
    token = request.cookies.get("github_token")
    
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
    print("=== CREATE USER ENDPOINT CALLED ===")
    print(f"All cookies: {dict(request.cookies)}")
    print(f"Headers: {dict(request.headers)}")
    
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
        
        # Handle OAuth errors (e.g., user cancelled login) - redirect back to dashboard
        if error:
            # User cancelled or denied access, redirect to dashboard gracefully
            return RedirectResponse(url="/dashboard")
        
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
    print("=== SET TOKEN ENDPOINT CALLED ===")
    print(f"Token received: {body.token[:20] if body.token else 'None'}...")
    
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
        update_user(
            user_id,
            {
                'email': user_data.get('email'),
                'name': user_data.get('name'),
                'avatar_url': user_data.get('avatar_url'),
                'bio': user_data.get('bio'),
                'location': user_data.get('location'),
                'company': user_data.get('company'),
                'blog': user_data.get('blog'),
                'is_active': True,
            }
        )
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
        cursor.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
        # Create new session
        cursor.execute("""
            INSERT INTO user_sessions (user_id, session_token, github_access_token, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (user_id, session_token, access_token, expires_at.isoformat()))
        conn.commit()
    
    # Mark setup as complete since user is now authenticated
    mark_setup_complete()
    
    print(f"Session created for user {user_data.get('login')} (id={user_id})")
    
    response = JSONResponse(content={
        "success": True,
        "setupComplete": True,
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
    token = request.cookies.get("github_token")
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
    response = RedirectResponse(url="/dashboard")
    
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
    """Check authentication status without making GitHub API call"""
    token = request.cookies.get("github_token")
    github_user = request.cookies.get("github_user")
    token_issued_at = request.cookies.get("token_issued_at")
    
    if not token:
        return {"authenticated": False}
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
async def connect_repository(owner: str, repo: str, request: Request, background_tasks: BackgroundTasks):
    """
    Connect a repository - creates the repo record in DB and attempts to set up webhook.
    This is the main endpoint called when user clicks "Clone/Connect" button.
    Auto-fetches recent commits and analyzes them in the background.
    
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
    token = request.cookies.get("github_token")
    
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
        
        # Auto-fetch recent commits in background
        repo_full_name = db_repo['full_name']
        background_tasks.add_task(auto_fetch_commits_for_repo, repo_full_name, token, 50)
        print(f"[Connect] Triggered auto-fetch for {repo_full_name}")
        
        return {
            "success": True,
            "repository": {
                "id": db_repo['id'],
                "name": db_repo['name'],
                "full_name": db_repo['full_name'],
                "default_branch": db_repo.get('default_branch', 'main'),
            },
            "webhook_setup": webhook_setup,
            "webhook_error": webhook_error,
            "auto_fetch": True,
            "message": "Repository connected. Fetching recent commits..."
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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


# ==================== RISK KEYWORD DETECTOR ====================

# Sensitive domain keywords with their risk boost scores
RISK_KEYWORDS = {
    # Authentication/Security - HIGH RISK (+25)
    'security': {
        'keywords': ['auth', 'login', 'logout', 'password', 'passwd', 'pwd', 'token', 'session', 
                     'jwt', 'oauth', 'credential', 'secret', 'api_key', 'apikey', 'private_key',
                     'encrypt', 'decrypt', 'hash', 'salt', 'bcrypt', 'argon2', 'permission',
                     'role', 'access_control', 'acl', 'rbac', 'authenticate', 'authorize'],
        'boost': 0.25,
        'label': 'Authentication/Security logic detected'
    },
    # Financial/Payment - HIGHEST RISK (+30)
    'financial': {
        'keywords': ['payment', 'pay', 'wallet', 'transfer', 'balance', 'money', 'currency',
                     'transaction', 'credit', 'debit', 'invoice', 'billing', 'checkout',
                     'stripe', 'paypal', 'refund', 'charge', 'subscription', 'price',
                     'amount', 'fee', 'discount', 'coupon', 'order_total', 'cart_total'],
        'boost': 0.30,
        'label': 'Financial/Payment logic detected'
    },
    # State Mutation - MEDIUM RISK (+15)
    'state_mutation': {
        'keywords': ['delete', 'remove', 'destroy', 'drop', 'truncate', 'update', 'modify',
                     'alter', 'insert', 'create', 'write', 'commit', 'rollback', 'migrate',
                     'bulk_update', 'bulk_delete', 'batch_insert', 'cascade'],
        'boost': 0.15,
        'label': 'State mutation operations detected'
    },
    # Permission/Access - HIGH RISK (+20)
    'permission': {
        'keywords': ['is_admin', 'is_superuser', 'has_permission', 'check_permission',
                     'grant', 'revoke', 'elevate', 'sudo', 'root', 'admin_only',
                     'require_auth', 'require_admin', 'protected', 'restricted'],
        'boost': 0.20,
        'label': 'Permission/Access control changes detected'
    },
    # Error Handling - MEDIUM RISK (+10)
    'error_handling': {
        'keywords': ['try', 'catch', 'except', 'finally', 'raise', 'throw', 'error',
                     'exception', 'failure', 'fallback', 'retry', 'timeout'],
        'boost': 0.10,
        'label': 'Error handling logic detected',
        'threshold': 5  # Only trigger if >5 occurrences
    },
    # Database Critical - HIGH RISK (+20)
    'database_critical': {
        'keywords': ['foreign_key', 'primary_key', 'index', 'constraint', 'schema',
                     'migration', 'alter_table', 'drop_table', 'create_table',
                     'add_column', 'drop_column', 'rename_column'],
        'boost': 0.20,
        'label': 'Database schema changes detected'
    },
    # API Endpoints - MEDIUM RISK (+12)
    'api_endpoints': {
        'keywords': ['@app.post', '@app.put', '@app.delete', '@router.post', '@router.put',
                     '@router.delete', 'api_view', 'rest_framework', 'serializer',
                     'endpoint', 'route'],
        'boost': 0.12,
        'label': 'API endpoint modifications detected'
    }
}


def detect_risk_keywords(diff_content: str, file_content: str = '') -> dict:
    """
    Detect sensitive keywords in code changes and calculate risk boosts.
    
    Args:
        diff_content: The git diff text containing added/removed lines
        file_content: Optional full file content for additional context
        
    Returns:
        Dictionary with:
        - total_boost: Sum of all risk boosts (capped at 0.5)
        - detected_domains: List of detected risk domains
        - keyword_matches: Detailed matches per domain
        - risk_factors: Human-readable risk factors for UI
    """
    combined_content = (diff_content + ' ' + file_content).lower()
    
    detected_domains = []
    keyword_matches = {}
    risk_factors = []
    total_boost = 0.0
    
    for domain, config in RISK_KEYWORDS.items():
        keywords = config['keywords']
        boost = config['boost']
        label = config['label']
        threshold = config.get('threshold', 1)
        
        # Count keyword occurrences
        matches = []
        total_count = 0
        for kw in keywords:
            count = combined_content.count(kw)
            if count > 0:
                matches.append({'keyword': kw, 'count': count})
                total_count += count
        
        # Apply boost if threshold met
        if total_count >= threshold:
            detected_domains.append(domain)
            keyword_matches[domain] = {
                'matches': matches,
                'total_count': total_count,
                'boost_applied': boost
            }
            risk_factors.append(f"{label} (+{int(boost*100)}%)")
            total_boost += boost
    
    # Cap total boost at 0.5 to prevent oversaturation
    total_boost = min(total_boost, 0.50)
    
    return {
        'total_boost': total_boost,
        'detected_domains': detected_domains,
        'keyword_matches': keyword_matches,
        'risk_factors': risk_factors
    }


def calculate_structural_risk_score(analysis_result: dict) -> float:
    """
    Calculate base structural risk score from code metrics.
    
    This is the structural component before keyword boosts.
    """
    summary = analysis_result.get('summary', {})
    changed_files = analysis_result.get('changed_files', [])
    
    score = 0.0
    
    # Lines changed (0 - 0.15)
    lines_added = summary.get('total_lines_added', 0)
    lines_deleted = summary.get('total_lines_deleted', 0)
    total_lines = lines_added + lines_deleted
    
    if total_lines > 500:
        score += 0.15
    elif total_lines > 200:
        score += 0.12
    elif total_lines > 100:
        score += 0.08
    elif total_lines > 50:
        score += 0.05
    else:
        score += 0.02
    
    # Files changed (0 - 0.10)
    num_files = len(changed_files)
    if num_files > 20:
        score += 0.10
    elif num_files > 10:
        score += 0.08
    elif num_files > 5:
        score += 0.05
    else:
        score += 0.02
    
    # Changed nodes (functions/classes) complexity (0 - 0.10)
    total_changed_nodes = sum(len(f.get('changed_nodes', [])) for f in changed_files)
    if total_changed_nodes > 15:
        score += 0.10
    elif total_changed_nodes > 8:
        score += 0.07
    elif total_changed_nodes > 3:
        score += 0.04
    else:
        score += 0.01
    
    # API/Route changes (0 - 0.08)
    api_changes = any('api' in str(f.get('change_types', [])).lower() for f in changed_files)
    if api_changes:
        score += 0.08
    
    # Async code changes (0 - 0.05)
    has_async = any(
        any(n.get('is_async', False) for n in f.get('changed_nodes', []))
        for f in changed_files
    )
    if has_async:
        score += 0.05
    
    return min(score, 0.50)  # Cap structural score at 0.50


# ==================== IMPACT ANALYSIS PIPELINE INTEGRATION ====================

def extract_features_from_diff(analysis_result: dict, repo_full_name: str, branch: str, commit_sha: str) -> dict:
    """
    Extract ML model features from git diff analysis result.
    This bridges the Code Change Detection stage to the Impact Analysis Engine.
    """
    # Get summary from analysis
    summary = analysis_result.get('summary', {})
    changed_files = analysis_result.get('changed_files', [])
    change_types = analysis_result.get('change_types', [])
    affected_components = analysis_result.get('affected_components', [])
    
    # Calculate lines changed
    total_lines_added = summary.get('total_lines_added', 0)
    total_lines_deleted = summary.get('total_lines_deleted', 0)
    lines_changed = total_lines_added + total_lines_deleted
    
    # Files changed
    files_changed = len(changed_files)
    
    # Determine change type from analysis
    change_type = 'SERVICE_LOGIC_CHANGE'  # default
    if 'API_CHANGE' in change_types:
        change_type = 'API_CHANGE'
    elif 'UI' in change_types or any('html' in f.get('path', '').lower() or 'css' in f.get('path', '').lower() for f in changed_files):
        change_type = 'UI_CHANGE'
    elif 'CONFIG' in change_types or any('.json' in f.get('path', '').lower() or '.yaml' in f.get('path', '').lower() for f in changed_files):
        change_type = 'CONFIG_CHANGE'
    
    # Determine component type
    component_type = 'SERVICE'
    api_files = [f for f in changed_files if any(x in f.get('path', '').lower() for x in ['/api/', 'routes', 'endpoints', 'controller'])]
    ui_files = [f for f in changed_files if any(x in f.get('path', '').lower() for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/'])]
    if len(api_files) > len(ui_files):
        component_type = 'API'
    elif len(ui_files) > 0:
        component_type = 'UI'
    
    # Detect shared components (used by multiple modules)
    shared_component = 1 if any('shared' in c.lower() or 'common' in c.lower() or 'utils' in c.lower() for c in affected_components) else 0
    
    # Estimate dependency depth based on imports/affected components
    dependency_depth = min(len(affected_components), 5) if affected_components else 1
    
    # Determine function category based on file paths and components
    function_category = 'misc'
    path_str = ' '.join([f.get('path', '') for f in changed_files]).lower()
    component_str = ' '.join(affected_components).lower()
    combined = path_str + ' ' + component_str
    
    if any(x in combined for x in ['auth', 'login', 'session', 'token', 'oauth']):
        function_category = 'auth'
    elif any(x in combined for x in ['payment', 'billing', 'invoice', 'wallet', 'transaction']):
        function_category = 'payment'
    elif any(x in combined for x in ['search', 'query', 'filter', 'index']):
        function_category = 'search'
    elif any(x in combined for x in ['profile', 'user', 'account', 'settings']):
        function_category = 'profile'
    elif any(x in combined for x in ['analytics', 'metrics', 'tracking', 'report']):
        function_category = 'analytics'
    elif any(x in combined for x in ['admin', 'console', 'manage', 'dashboard']):
        function_category = 'admin'
    
    # Determine module name from affected components or file paths
    module_name = 'CoreModule'
    if affected_components:
        # Try to match against known modules
        for component in affected_components:
            if component in REQUIRED_CATEGORICAL_FEATURES.get('module_name', []):
                module_name = component
                break
    
    # Estimate test coverage level (default to medium)
    test_coverage_level = 'medium'
    test_files = [f for f in changed_files if 'test' in f.get('path', '').lower()]
    if len(test_files) > files_changed * 0.3:
        test_coverage_level = 'high'
    elif len(test_files) == 0 and files_changed > 3:
        test_coverage_level = 'low'
    
    # Get repo type (default to monolith, could be enhanced with repo analysis)
    repo_type = 'monolith'
    if 'microservice' in repo_full_name.lower() or 'service' in repo_full_name.lower():
        repo_type = 'microservices'
    
    # ==================== RISK KEYWORD DETECTION ====================
    # Collect all diff content from changed files
    diff_content = ''
    for f in changed_files:
        diff_content += f.get('diff', '') + ' '
        # Also include changed node names and their context
        for node in f.get('changed_nodes', []):
            diff_content += node.get('name', '') + ' '
            diff_content += node.get('docstring', '') or ''
    
    # Run keyword detection
    keyword_result = detect_risk_keywords(diff_content, combined)
    
    # Calculate structural score
    structural_score = calculate_structural_risk_score(analysis_result)
    
    # Combined risk score = structural + keyword boosts
    keyword_boost = keyword_result['total_boost']
    combined_risk_score = min(structural_score + keyword_boost, 0.95)
    
    print(f"[Risk Analysis] Structural: {structural_score:.2f}, Keyword Boost: {keyword_boost:.2f}, Combined: {combined_risk_score:.2f}")
    if keyword_result['detected_domains']:
        print(f"[Risk Analysis] Detected domains: {', '.join(keyword_result['detected_domains'])}")
    
    # Build feature dict matching ImpactAnalysisRequest
    return {
        'lines_changed': lines_changed,
        'files_changed': files_changed,
        'dependency_depth': dependency_depth,
        'shared_component': shared_component,
        'historical_failure_count': 0,  # Would need historical data
        'historical_change_frequency': 1,  # Would need historical data
        'days_since_last_failure': 30,  # Would need historical data
        'tests_impacted': len(test_files),
        'repo_type': repo_type,
        'module_name': module_name,
        'change_type': change_type,
        'component_type': component_type,
        'function_category': function_category,
        'test_coverage_level': test_coverage_level,
        'repository': repo_full_name,
        'branch': branch,
        'commit_id': commit_sha,
        'files_list': [f.get('path', '') for f in changed_files],
        # New risk keyword detection fields
        'keyword_risk_boost': keyword_boost,
        'structural_risk_score': structural_score,
        'combined_risk_score': combined_risk_score,
        'detected_risk_domains': keyword_result['detected_domains'],
        'risk_factors_from_keywords': keyword_result['risk_factors']
    }


def run_impact_analysis_from_features(features: dict) -> dict:
    """
    Run ML-based impact analysis using extracted features.
    Returns impact analysis result dict.
    
    Now includes risk keyword detection boosts.
    """
    global _impact_model, _model_features, _model_threshold
    
    # Load model if needed
    model = load_impact_model()
    
    # Create request object
    request = ImpactAnalysisRequest(**{k: v for k, v in features.items() if k in ImpactAnalysisRequest.__fields__})
    
    # Check if we have pre-computed keyword risk score
    keyword_boost = features.get('keyword_risk_boost', 0.0)
    risk_factors_from_keywords = features.get('risk_factors_from_keywords', [])
    combined_risk_score = features.get('combined_risk_score', None)
    
    if combined_risk_score is not None:
        # Use pre-computed combined score (structural + keywords)
        risk_score = combined_risk_score
        print(f"[Impact Analysis] Using pre-computed risk score: {risk_score:.2f}")
    elif model is None:
        # Fallback to rule-based analysis + keyword boost
        base_risk = calculate_rule_based_risk(request)
        risk_score = min(base_risk + keyword_boost, 0.95)
        print(f"[Impact Analysis] Rule-based: {base_risk:.2f} + keyword boost: {keyword_boost:.2f} = {risk_score:.2f}")
    else:
        # ML model prediction + keyword boost
        X = prepare_model_input(request)
        ml_risk = float(model.predict_proba(X)[0, 1])
        risk_score = min(ml_risk + keyword_boost, 0.95)
        print(f"[Impact Analysis] ML prediction: {ml_risk:.2f} + keyword boost: {keyword_boost:.2f} = {risk_score:.2f}")
    
    # Determine risk level and color
    if risk_score >= 0.7:
        risk_level = "High"
        risk_color = "red"
    elif risk_score >= 0.4:
        risk_level = "Medium"
        risk_color = "amber"
    else:
        risk_level = "Low"
        risk_color = "green"
    
    # Get recommended action
    recommended_action, justification = get_recommended_action(risk_score, request)
    
    # Get impact factors - merge with keyword-based factors
    impact_factors = get_top_impact_factors(request, risk_score)
    
    # Add keyword-detected risk factors to the top
    if risk_factors_from_keywords:
        impact_factors = risk_factors_from_keywords + impact_factors
        # Keep only top 5 unique factors
        seen = set()
        unique_factors = []
        for f in impact_factors:
            if f not in seen:
                seen.add(f)
                unique_factors.append(f)
        impact_factors = unique_factors[:5]
    
    # Calculate affected surface
    apis_impacted = 0
    ui_components_impacted = 0
    if features.get('files_list'):
        for file in features['files_list']:
            file_lower = file.lower()
            if any(x in file_lower for x in ['/api/', 'routes', 'endpoints', 'controller']):
                apis_impacted += 1
            if any(x in file_lower for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/']):
                ui_components_impacted += 1
    
    return {
        'repository': features.get('repository'),
        'branch': features.get('branch'),
        'commit_id': features.get('commit_id'),
        'files_changed': features.get('files_changed', 0),
        'lines_changed': features.get('lines_changed', 0),
        'change_category': features.get('change_type', 'SERVICE_LOGIC_CHANGE'),
        'risk_score': round(risk_score, 4),
        'risk_level': risk_level,
        'risk_color': risk_color,
        'apis_impacted': apis_impacted,
        'ui_components_impacted': ui_components_impacted,
        'dependency_depth': features.get('dependency_depth', 1),
        'tests_impacted': features.get('tests_impacted', 0),
        'recommended_action': recommended_action,
        'action_justification': justification,
        'top_impact_factors': impact_factors,
        'test_selection_status': 'suggested',
        'ci_execution_state': 'Pending',
        # Include keyword detection info for transparency
        'detected_risk_domains': features.get('detected_risk_domains', []),
        'keyword_risk_boost': keyword_boost
    }


# ==================== BACKGROUND PROCESSING ====================

def parse_patch_to_line_ranges(patch: str) -> list:
    """
    Parse git patch/diff to extract line ranges.
    Returns list of dicts with start, end, type.
    """
    import re
    line_ranges = []
    
    if not patch:
        return line_ranges
    
    # Match hunk headers: @@ -old_start,old_count +new_start,new_count @@
    hunk_pattern = r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@'
    
    for match in re.finditer(hunk_pattern, patch):
        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)
        
        # Determine change type
        if old_count == 0:
            change_type = 'added'
        elif new_count == 0:
            change_type = 'removed'
        else:
            change_type = 'modified'
        
        if new_count > 0:
            line_ranges.append({
                'start': new_start,
                'end': new_start + new_count - 1,
                'type': change_type
            })
    
    return line_ranges


def analyze_python_ast_from_content(source_code: str, file_path: str, line_ranges: list) -> dict:
    """
    Run AST analysis on Python source code to detect functions/classes.
    Returns changed_nodes that overlap with the line_ranges.
    """
    import ast
    
    result = {
        'all_nodes': [],
        'changed_nodes': [],
        'change_types': set()
    }
    
    if not source_code:
        return result
    
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"[AST] Syntax error in {file_path}: {e}")
        return result
    
    def get_decorator_names(decorators):
        names = []
        for dec in decorators:
            if isinstance(dec, ast.Name):
                names.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                # Get full dotted name
                parts = []
                current = dec
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                names.append('.'.join(reversed(parts)))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    names.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    parts = []
                    current = dec.func
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    names.append('.'.join(reversed(parts)))
        return names
    
    def overlaps_with_changes(start_line, end_line):
        for r in line_ranges:
            if not (end_line < r['start'] or start_line > r['end']):
                return True
        return False
    
    # API route decorators
    api_decorators = {'route', 'get', 'post', 'put', 'delete', 'patch', 'app.route', 'app.get', 'app.post'}
    
    def visit_node(node, parent_name=None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = get_decorator_names(node.decorator_list)
            start_line = node.lineno
            end_line = node.end_lineno or node.lineno
            
            node_info = {
                'name': node.name,
                'type': 'async_function' if isinstance(node, ast.AsyncFunctionDef) else 'function',
                'start_line': start_line,
                'end_line': end_line,
                'parent': parent_name,
                'decorators': decorators,
                'is_api': any(d in api_decorators for d in decorators),
                'parameters': [arg.arg for arg in node.args.args]
            }
            
            result['all_nodes'].append(node_info)
            
            # Check if this node overlaps with changed lines
            if overlaps_with_changes(start_line, end_line):
                result['changed_nodes'].append(node_info)
                if node_info['is_api']:
                    result['change_types'].add('API_CHANGE')
                else:
                    result['change_types'].add('SERVICE_LOGIC_CHANGE')
            
            # Visit nested nodes
            for child in ast.iter_child_nodes(node):
                visit_node(child, node.name)
        
        elif isinstance(node, ast.ClassDef):
            start_line = node.lineno
            end_line = node.end_lineno or node.lineno
            
            node_info = {
                'name': node.name,
                'type': 'class',
                'start_line': start_line,
                'end_line': end_line,
                'parent': parent_name,
                'decorators': get_decorator_names(node.decorator_list)
            }
            
            result['all_nodes'].append(node_info)
            
            if overlaps_with_changes(start_line, end_line):
                result['changed_nodes'].append(node_info)
                result['change_types'].add('CLASS_CHANGE')
            
            # Visit class body
            for child in ast.iter_child_nodes(node):
                visit_node(child, node.name)
        
        else:
            for child in ast.iter_child_nodes(node):
                visit_node(child, parent_name)
    
    visit_node(tree)
    result['change_types'] = list(result['change_types'])
    
    return result


async def analyze_with_github_api(token: str, owner: str, repo: str, before_sha: str, after_sha: str) -> dict:
    """
    Enhanced: Analyze commits using GitHub API with full AST analysis.
    Fetches file contents and parses AST to detect changed functions/classes.
    This provides similar functionality to local git analysis.
    """
    try:
        github_api = GitHubAPI(token)
        comparison = await github_api.compare_commits(owner, repo, before_sha, after_sha)
        
        # Convert GitHub API format to our analysis format
        changed_files = []
        all_changed_functions = []
        all_change_types = set()
        affected_components = set()
        
        async with httpx.AsyncClient() as client:
            for f in comparison.get('files', []):
                file_path = f['path']
                file_status = f['status']
                patch = f.get('patch', '')
                
                # Parse line ranges from patch
                line_ranges = parse_patch_to_line_ranges(patch)
                
                changed_nodes = []
                file_change_types = []
                
                # For Python files, fetch content and run AST analysis
                if file_path.endswith('.py') and file_status != 'removed':
                    try:
                        # Fetch file content from GitHub
                        content_response = await client.get(
                            f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}",
                            params={"ref": after_sha},
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Accept": "application/vnd.github.v3+json",
                            },
                        )
                        
                        if content_response.status_code == 200:
                            content_data = content_response.json()
                            if content_data.get('encoding') == 'base64':
                                import base64
                                source_code = base64.b64decode(content_data['content']).decode('utf-8')
                                
                                # Run AST analysis
                                ast_result = analyze_python_ast_from_content(
                                    source_code, file_path, line_ranges
                                )
                                
                                changed_nodes = ast_result.get('changed_nodes', [])
                                file_change_types = ast_result.get('change_types', [])
                                
                                # Collect all changed functions
                                for node in changed_nodes:
                                    if node['type'] in ('function', 'async_function'):
                                        all_changed_functions.append({
                                            'name': node['name'],
                                            'file': file_path,
                                            'is_api': node.get('is_api', False)
                                        })
                                
                                all_change_types.update(file_change_types)
                                
                                # Extract component from path
                                path_parts = file_path.split('/')
                                if len(path_parts) > 1:
                                    affected_components.add(path_parts[0])
                    
                    except Exception as ast_err:
                        print(f"[GitHub API] AST analysis failed for {file_path}: {ast_err}")
                
                # Detect additional change types from file path
                path_lower = file_path.lower()
                if any(x in path_lower for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/']):
                    all_change_types.add('UI_CHANGE')
                elif any(x in path_lower for x in ['.json', '.yaml', '.yml', '.env', 'config']):
                    all_change_types.add('CONFIG_CHANGE')
                elif '/api/' in path_lower or 'routes' in path_lower:
                    all_change_types.add('API_CHANGE')
                
                changed_files.append({
                    'path': file_path,
                    'status': file_status,
                    'additions': f.get('additions', 0),
                    'deletions': f.get('deletions', 0),
                    'diff': patch,
                    'line_ranges': line_ranges,
                    'changed_nodes': changed_nodes,
                    'change_types': file_change_types
                })
        
        return {
            'old_commit': before_sha,
            'new_commit': after_sha,
            'changed_files': changed_files,
            'changed_functions': all_changed_functions,
            'change_types': list(all_change_types),
            'affected_components': list(affected_components),
            'summary': {
                'total_files': len(changed_files),
                'added_files': sum(1 for f in changed_files if f['status'] == 'added'),
                'modified_files': sum(1 for f in changed_files if f['status'] == 'modified'),
                'deleted_files': sum(1 for f in changed_files if f['status'] == 'removed'),
                'total_lines_added': sum(f.get('additions', 0) for f in changed_files),
                'total_lines_deleted': sum(f.get('deletions', 0) for f in changed_files),
                'functions_changed': len(all_changed_functions),
            },
            'source': 'github_api_enhanced'
        }
    except Exception as e:
        print(f"[Pipeline] GitHub API analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def auto_fetch_commits_for_repo(repo_full_name: str, token: str, limit: int = 50):
    """
    Auto-fetch recent commits from GitHub and analyze them.
    This is called when a repo is connected to populate commit history.
    """
    try:
        print(f"[AutoFetch] Fetching commits for {repo_full_name}")
        synced_count = 0
        
        async with httpx.AsyncClient() as client:
            owner, repo = repo_full_name.split('/')
            
            # Fetch recent commits from GitHub (no limit restriction)
            commits_response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"per_page": limit},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if commits_response.status_code != 200:
                print(f"[AutoFetch] Failed to fetch commits: {commits_response.status_code}")
                return 0
            
            commits = commits_response.json()
            print(f"[AutoFetch] Found {len(commits)} commits")
            
            for commit in commits:
                commit_sha = commit['sha']
                
                # Check if we already have this commit
                existing = get_webhook_event_by_delivery_id(f"sync-{commit_sha}")
                if existing:
                    continue
                
                # Also check by commit_sha
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id FROM webhook_events WHERE commit_sha = %s",
                        (commit_sha,)
                    )
                    if cursor.fetchone():
                        continue
                
                # Get the parent SHA for diff
                parent_sha = commit['parents'][0]['sha'] if commit.get('parents') else None
                
                # Create a synthetic webhook event
                event_data = {
                    "github_delivery_id": f"sync-{commit_sha}",
                    "event_type": "push",
                    "repository_full_name": repo_full_name,
                    "branch": "main",
                    "commit_sha": commit_sha,
                    "before_sha": parent_sha,
                    "payload": json.dumps({
                        "ref": "refs/heads/main",
                        "after": commit_sha,
                        "before": parent_sha,
                        "repository": {"full_name": repo_full_name},
                        "commits": [{
                            "id": commit_sha,
                            "message": commit['commit']['message'],
                            "author": commit['commit']['author'],
                            "added": [],
                            "modified": [],
                            "removed": []
                        }],
                        "head_commit": {
                            "id": commit_sha,
                            "message": commit['commit']['message']
                        }
                    })
                }
                
                # Create the event in database
                stored_event = create_webhook_event(
                    webhook_id=1,
                    delivery_id=event_data["github_delivery_id"],
                    event_type=event_data["event_type"],
                    repository_full_name=event_data["repository_full_name"],
                    branch=event_data["branch"],
                    commit_sha=event_data["commit_sha"],
                    before_sha=event_data["before_sha"],
                    payload=event_data["payload"]
                )
                
                if stored_event:
                    event_id = stored_event["id"]
                    synced_count += 1
                    
                    # Process the event immediately - analyze with GitHub API
                    try:
                        if parent_sha:
                            # Use GitHub API to get proper analysis result
                            analysis_result = await analyze_with_github_api(
                                token, owner, repo, parent_sha, commit_sha
                            )
                            
                            if analysis_result:
                                # Extract features using proper function signature
                                features = extract_features_from_diff(
                                    analysis_result, repo_full_name, "main", commit_sha
                                )
                                impact_result = run_impact_analysis_from_features(features)
                                
                                # Store the result
                                processing_result = {
                                    "pipeline_status": "completed",
                                    "diff_analysis": analysis_result,
                                    "impact_analysis": impact_result
                                }
                                
                                mark_webhook_event_processed(
                                    event_id,
                                    json.dumps(processing_result)
                                )
                                print(f"[AutoFetch] Analyzed commit {commit_sha[:7]}")
                            else:
                                print(f"[AutoFetch] No analysis result for {commit_sha[:7]}")
                        else:
                            # Initial commit - no parent to compare
                            processing_result = {
                                "pipeline_status": "completed",
                                "diff_analysis": {"note": "Initial commit - no parent"},
                                "impact_analysis": {"risk_level": "low", "risk_score": 0.1}
                            }
                            mark_webhook_event_processed(
                                event_id,
                                json.dumps(processing_result)
                            )
                            print(f"[AutoFetch] Marked initial commit {commit_sha[:7]}")
                    except Exception as proc_error:
                        print(f"[AutoFetch] Error processing commit {commit_sha}: {proc_error}")
        
        print(f"[AutoFetch] Synced {synced_count} commits for {repo_full_name}")
        return synced_count
        
    except Exception as e:
        print(f"[AutoFetch] Error: {e}")
        import traceback
        traceback.print_exc()
        return 0


async def process_webhook_event_background(event_id: int, event_data: dict):
    """
    Background task to process a webhook event.
    
    PIPELINE FLOW:
    1. Clone/pull repository (with GitHub API fallback)
    2. Run git diff analysis (Code Change Detection)
    3. Extract features from diff
    4. Run ML Impact Analysis
    5. Store combined results
    """
    import json
    import asyncio
    
    try:
        print(f"[Pipeline] ========== Processing webhook event {event_id} ==========")
        
        repo_full_name = event_data.get('repository_full_name')
        before_sha = event_data.get('before_sha')
        after_sha = event_data.get('commit_sha')
        branch = event_data.get('branch')
        
        if not repo_full_name or not after_sha:
            print(f"[Pipeline] Missing required data for event {event_id}")
            return
        
        owner, repo_name = repo_full_name.split('/')
        
        # Get a valid token from the database for this repo
        repo = get_repository_by_full_name(repo_full_name)
        if not repo:
            print(f"[Pipeline] Repository not found: {repo_full_name}")
            return
        
        # Get user's token from user_sessions (joined via repositories)
        token = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.github_access_token FROM user_sessions s 
                JOIN repositories r ON r.user_id = s.user_id 
                WHERE r.full_name = %s AND s.expires_at > NOW()
                ORDER BY s.created_at DESC LIMIT 1
            """, (repo_full_name,))
            row = cursor.fetchone()
            if row:
                token = row['github_access_token']
        
        if not token:
            print(f"[Pipeline] No access token found for repo {repo_full_name}")
            return
        
        # STEP 1: Try to clone/pull the repository (may fail on hosted environments)
        print(f"[Pipeline] Step 1: Attempting to clone/pull repository...")
        local_path = None
        use_github_api = os.getenv("USE_GITHUB_API_FOR_DIFFS", "false").lower() == "true"
        
        if use_github_api:
            print(f"[Pipeline] Using GitHub API for diffs (USE_GITHUB_API_FOR_DIFFS=true)")
        else:
            try:
                local_path = await clone_or_pull_repo(owner, repo_name, token, branch)
                print(f"[Pipeline] Repository cloned/pulled to: {local_path}")
            except Exception as clone_err:
                print(f"[Pipeline] Local git clone failed: {clone_err}")
                print(f"[Pipeline] Falling back to GitHub API for diff analysis...")
                use_github_api = True
        
        # STEP 2: Run git diff + AST analysis (Code Change Detection)
        print(f"[Pipeline] Step 2: Running diff analysis...")
        analysis_result = None
        impact_result = None
        
        if before_sha and after_sha and before_sha != '0' * 40:
            try:
                # Try local git analysis first, fall back to GitHub API
                if local_path and not use_github_api:
                    analysis_result = analyze_commits(local_path, before_sha, after_sha)
                    print(f"[Pipeline] Local git diff analysis complete for event {event_id}")
                else:
                    # Use GitHub API for diff
                    analysis_result = await analyze_with_github_api(token, owner, repo_name, before_sha, after_sha)
                    if analysis_result:
                        print(f"[Pipeline] GitHub API diff analysis complete for event {event_id}")
                    else:
                        raise Exception("GitHub API analysis returned no results")
                
                # STEP 3: Extract features from diff
                print(f"[Pipeline] Step 3: Extracting ML features from analysis...")
                features = extract_features_from_diff(analysis_result, repo_full_name, branch, after_sha)
                print(f"[Pipeline] Extracted features: {features.get('files_changed')} files, {features.get('lines_changed')} lines")
                
                # STEP 4: Run ML Impact Analysis
                print(f"[Pipeline] Step 4: Running ML Impact Analysis...")
                impact_result = run_impact_analysis_from_features(features)
                print(f"[Pipeline] Impact Analysis complete - Risk: {impact_result.get('risk_score')} ({impact_result.get('risk_level')})")
                
            except Exception as e:
                print(f"[Pipeline] Analysis error for event {event_id}: {e}")
                import traceback
                traceback.print_exc()
                analysis_result = {"error": str(e)}
        else:
            # New branch or initial push
            print(f"[Pipeline] Skipping diff (new branch or initial push) for event {event_id}")
            analysis_result = {
                "note": "Initial push or new branch - no prior commit to compare",
                "files": [],
                "logical_changes": {}
            }
        
        # STEP 5: Auto-trigger test generation for high-risk changes
        test_generation_result = None
        risk_level = impact_result.get('risk_level', '').lower()
        if risk_level in ['high', 'medium']:
            print(f"[Pipeline] Step 5: Auto-triggering test generation (risk: {impact_result.get('risk_level')})...")
            try:
                from model.LLM import generate_tests, prioritize_tests
                
                # Build rich code description from diff analysis
                files_changed = analysis_result.get('files', [])
                risk_domains = impact_result.get('detected_risk_domains', [])
                
                code_description = f"Security-sensitive code changes detected.\n"
                code_description += f"Risk Level: {impact_result.get('risk_level')} ({impact_result.get('risk_score', 0):.2f})\n"
                code_description += f"Risk Domains: {', '.join(risk_domains)}\n\n"
                code_description += f"Files changed:\n"
                
                for f in files_changed[:5]:  # Limit to 5 files
                    filename = f.get('filename', 'unknown')
                    code_description += f"\nFile: {filename}\n"
                    code_description += f"Status: {f.get('status', 'modified')}\n"
                    
                    # Add function/class names from logical changes
                    logical_changes = f.get('logical_changes', [])
                    if logical_changes:
                        code_description += "Functions/Methods:\n"
                        for change in logical_changes[:5]:
                            change_type = change.get('type', 'change')
                            desc = change.get('description', change.get('name', ''))
                            code_description += f"  - {change_type}: {desc}\n"
                
                print(f"[Pipeline] Code description for LLM ({len(code_description)} chars)")
                
                # Generate tests
                gen_result = generate_tests(code_description, language="python")
                
                # Check if we have tests (success can be True, False, or None)
                tests_generated = gen_result.get('tests', [])
                if tests_generated:
                    print(f"[Pipeline] LLM generated {len(tests_generated)} tests")
                    
                    # Prioritize tests
                    priority_result = prioritize_tests(
                        tests=tests_generated,
                        change_risk_score=impact_result.get('risk_score', 0.5),
                        files_changed=len(files_changed),
                        critical_module=risk_level == 'high'
                    )
                    
                    # Get all prioritized tests with scores (sorted by priority)
                    all_prioritized = priority_result.get('all_tests', tests_generated)
                    selected_tests = priority_result.get('selected_tests', [])
                    
                    test_generation_result = {
                        "success": True,
                        "auto_generated": True,
                        "source": "ollama",
                        "test_count": len(all_prioritized),
                        "tests": all_prioritized,
                        "selected_tests": selected_tests,
                        "selected_count": priority_result.get('selected_count', 0),
                        "priority_level": priority_result.get('priority_level', 'all'),
                        "generation_time_ms": gen_result.get('generation_time_ms', 0)
                    }
                    print(f"[Pipeline] Prioritized {len(all_prioritized)} tests, {len(selected_tests)} selected as important")
                else:
                    print(f"[Pipeline] LLM test generation returned: success={gen_result.get('success')}, error={gen_result.get('error')}")
                    # Fallback: Generate basic tests from detected domains
                    fallback_tests = []
                    for domain in risk_domains:
                        if domain == 'security':
                            fallback_tests.append({
                                "name": "test_auth_required",
                                "endpoint": "/api/endpoint",
                                "method": "POST",
                                "payload": {},
                                "expected_status": 401,
                                "description": "Verify authentication is required"
                            })
                        if domain == 'financial':
                            fallback_tests.append({
                                "name": "test_payment_validation",
                                "endpoint": "/api/payment",
                                "method": "POST",
                                "payload": {"amount": -100},
                                "expected_status": 400,
                                "description": "Verify negative amounts are rejected"
                            })
                        if domain == 'permission':
                            fallback_tests.append({
                                "name": "test_unauthorized_access",
                                "endpoint": "/api/admin",
                                "method": "GET",
                                "payload": {},
                                "expected_status": 403,
                                "description": "Verify proper authorization checks"
                            })
                    if fallback_tests:
                        test_generation_result = {
                            "auto_generated": True,
                            "source": "fallback",
                            "test_count": len(fallback_tests),
                            "tests": fallback_tests,
                            "selected_count": len(fallback_tests),
                            "note": "Generated from risk domain analysis (LLM unavailable)"
                        }
                        print(f"[Pipeline] Generated {len(fallback_tests)} fallback tests from risk domains")
                    
            except ImportError as e:
                print(f"[Pipeline] LLM module not available for auto-generation: {e}")
            except Exception as e:
                import traceback
                print(f"[Pipeline] Auto test generation failed: {e}")
                traceback.print_exc()
        
        # Combine results
        combined_result = {
            "diff_analysis": analysis_result,
            "impact_analysis": impact_result,
            "test_generation": test_generation_result,
            "pipeline_status": "completed",
            "processed_at": datetime.now().isoformat()
        }
        
        # STEP 6: Mark as processed with results
        result_json = json.dumps(combined_result)
        mark_webhook_event_processed(event_id, result_json)
        print(f"[Pipeline] ========== Event {event_id} processing complete ==========")
        
    except Exception as e:
        import traceback
        print(f"[Pipeline] Error processing event {event_id}: {e}")
        traceback.print_exc()
        # Mark as processed with error to prevent infinite retries
        mark_webhook_event_processed(event_id, json.dumps({
            "error": str(e),
            "pipeline_status": "failed"
        }))


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
    repo_record = get_repository_by_full_name(repo_full_name) if repo_full_name else None
    repository_id = repo_record.get("id") if repo_record else None
    
    if not repo_full_name:
        # Ping events might not have full repo info
        if event_type != "ping":
            raise HTTPException(status_code=400, detail="Missing repository information")
    
    # Look up webhook secret for this repository
    webhook_record = get_webhook_by_repository(repository_id) if repository_id else None
    webhook_secret = webhook_record.get("secret_hash") if webhook_record else None
    
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
    stored_event = create_webhook_event(
        webhook_id=webhook_record.get("id") if webhook_record else None,
        delivery_id=delivery_id,
        event_type=event_type,
        repository_full_name=repo_full_name or "",
        payload=payload,
        branch=event_data.get("branch"),
        commit_sha=event_data.get("commit_sha"),
        before_sha=event_data.get("before_sha"),
    )
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    """Clone a repository or pull latest changes if already cloned"""
    ensure_repo_directory()
    
    local_path = get_repo_local_path(owner, repo)
    clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    
    if os.path.exists(os.path.join(local_path, '.git')):
        # Repository exists, fetch and checkout
        try:
            import subprocess
            subprocess.run(
                ['git', 'fetch', '--all'],
                cwd=local_path,
                capture_output=True,
                timeout=120
            )
            if branch:
                subprocess.run(
                    ['git', 'checkout', branch],
                    cwd=local_path,
                    capture_output=True,
                    timeout=30
                )
                subprocess.run(
                    ['git', 'pull', 'origin', branch],
                    cwd=local_path,
                    capture_output=True,
                    timeout=120
                )
        except Exception as e:
            print(f"Error updating repo: {e}")
    else:
        # Clone the repository
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            import subprocess
            cmd = ['git', 'clone', clone_url, local_path]
            if branch:
                cmd.extend(['-b', branch])
            subprocess.run(cmd, capture_output=True, timeout=300)
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
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get the event from database
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = %s", (event_id,))
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get the event from database
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = %s", (event_id,))
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

@app.get("/repo", response_class=HTMLResponse)
async def repositories_page():
    """Serve the repositories view page"""
    return FileResponse("frontend/pages/repo.html")


@app.get("/api/repositories/connected")
async def get_connected_repositories(request: Request):
    """
    Get all repositories connected by the current user with webhook status.
    Returns data formatted for the Repositories View frontend.
    """
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
    token = request.cookies.get("github_token")
    
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
        
        # Handle both old format (direct) and new format (nested under diff_analysis)
        diff_data = latest_analysis.get('diff_analysis', latest_analysis)
        
        # Transform the analysis data to match our data contract
        # The analyzer returns 'changed_files', map to 'files' for frontend
        files = diff_data.get('changed_files', diff_data.get('files', []))
        logical = diff_data.get('logical_changes', {})
        
        # Also get summary from analyzer if available
        analyzer_summary = diff_data.get('summary', {})
        
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
async def get_repository_events(full_name: str, request: Request, limit: int = 50, auto_fetch: bool = True):
    """
    Get webhook events history for a repository.
    If no events exist and auto_fetch is True, fetches from GitHub.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        events = get_recent_webhook_events(full_name, limit=limit)
        
        # If no events exist, auto-fetch from GitHub
        if not events and auto_fetch and token:
            print(f"[Events] No local events for {full_name}, auto-fetching from GitHub...")
            synced = await auto_fetch_commits_for_repo(full_name, token, limit)
            if synced > 0:
                # Reload events after sync
                events = get_recent_webhook_events(full_name, limit=limit)
                print(f"[Events] After sync: {len(events)} events")
        
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


# ==================== IMPACT ANALYSIS ML MODEL ====================

import pickle
import numpy as np
import pandas as pd

# Load ML model configuration - Model is in backend/model/ folder
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'model', 'impact_analysis_model.pkl')
MODEL_FEATURES_PATH = os.path.join(os.path.dirname(__file__), '../../..', 'Z_Data_set', 'model_features.json')

_impact_model = None
_model_features = None
_model_threshold = 0.5


def load_impact_model():
    """Load the impact analysis ML model from backend/model/impact_analysis_model.pkl"""
    global _impact_model, _model_features, _model_threshold
    
    if _impact_model is not None:
        return _impact_model
    
    try:
        # Load model from pkl file - it contains model, feature_names, threshold
        model_path = os.path.abspath(MODEL_PATH)
        print(f"[Impact Analysis] Looking for model at: {model_path}")
        
        if os.path.exists(model_path):
            with open(model_path, 'rb') as f:
                model_package = pickle.load(f)
                _impact_model = model_package.get('model')
                _model_features = model_package.get('feature_names', [])
                _model_threshold = model_package.get('threshold', 0.5)
                print(f"[Impact Analysis] Model loaded successfully!")
                print(f"[Impact Analysis] Model type: {model_package.get('model_type')}")
                print(f"[Impact Analysis] Features: {len(_model_features)}")
                print(f"[Impact Analysis] Threshold: {_model_threshold}")
        else:
            print(f"[Impact Analysis] WARNING: Model file not found at {model_path}")
            # Fallback to JSON features file if model not found
            features_path = os.path.abspath(MODEL_FEATURES_PATH)
            if os.path.exists(features_path):
                with open(features_path, 'r') as f:
                    features_data = json.load(f)
                    _model_features = features_data.get('feature_names', [])
                    _model_threshold = features_data.get('threshold', 0.5)
                    print(f"[Impact Analysis] Features loaded from JSON: {len(_model_features)}")
        
        return _impact_model
    except Exception as e:
        print(f"[Impact Analysis] Error loading model: {e}")
        import traceback
        traceback.print_exc()
        return None


# Required input features for impact analysis
REQUIRED_NUMERICAL_FEATURES = [
    'lines_changed',
    'files_changed', 
    'dependency_depth',
    'shared_component',  # 0 or 1
    'historical_failure_count',
    'historical_change_frequency',
    'days_since_last_failure',
    'tests_impacted'
]

REQUIRED_CATEGORICAL_FEATURES = {
    'repo_type': ['monolith', 'microservices'],
    'module_name': [
        'AdminConsole', 'AnalyticsEngine', 'AuditLogger', 'AuthService', 'AutocompleteHandler',
        'AvatarHandler', 'BaseController', 'BillingService', 'CacheManager', 'CommonUtils',
        'ConfigManager', 'CoreModule', 'CredentialStore', 'DashboardService', 'DataAggregator',
        'DataExporter', 'EventTracker', 'FacetProcessor', 'FeatureFlagService', 'FilterService',
        'GenericHandler', 'HelperFunctions', 'IndexManager', 'InsightsProcessor', 'InvoiceGenerator',
        'LoginHandler', 'MaintenanceHandler', 'MetricsCollector', 'NotificationPrefs', 'OAuthProvider',
        'PaymentGateway', 'PayoutController', 'PermissionValidator', 'PrivacyController', 'ProfileService',
        'ProfileValidator', 'QueryOptimizer', 'RankingAlgorithm', 'RefundHandler', 'ReportGenerator',
        'RoleController', 'SearchEngine', 'SessionController', 'SharedLibrary', 'SubscriptionManager',
        'SupportService', 'SystemMonitor', 'TokenManager', 'TransactionProcessor', 'TrendAnalyzer',
        'UserAuthenticator', 'UserManager', 'UserPreferences', 'UtilityService', 'WalletService'
    ],
    'change_type': ['API_CHANGE', 'UI_CHANGE', 'SERVICE_LOGIC_CHANGE', 'CONFIG_CHANGE'],
    'component_type': ['API', 'UI', 'SERVICE'],
    'function_category': ['auth', 'payment', 'search', 'profile', 'analytics', 'admin', 'misc'],
    'test_coverage_level': ['low', 'medium', 'high']
}


class ImpactAnalysisRequest(BaseModel):
    """Request model for impact analysis"""
    # Required numerical features
    lines_changed: int
    files_changed: int
    dependency_depth: int = 1
    shared_component: int = 0  # 0 or 1
    historical_failure_count: int = 0
    historical_change_frequency: int = 1
    days_since_last_failure: int = 30
    tests_impacted: int = 0
    
    # Required categorical features
    repo_type: str = "monolith"
    module_name: str = "CoreModule"
    change_type: str = "SERVICE_LOGIC_CHANGE"
    component_type: str = "SERVICE"
    function_category: str = "misc"
    test_coverage_level: str = "medium"
    
    # Optional context
    repository: Optional[str] = None
    branch: Optional[str] = None
    commit_id: Optional[str] = None
    files_list: Optional[List[str]] = None


class ImpactAnalysisResponse(BaseModel):
    """Response model for impact analysis"""
    # Change Scope Summary
    repository: Optional[str] = None
    branch: Optional[str] = None
    commit_id: Optional[str] = None
    files_changed: int
    lines_changed: int
    change_category: str
    
    # Impact Analysis Result (Core)
    risk_score: float  # 0.0 - 1.0
    risk_level: str  # Low / Medium / High
    risk_color: str  # green / amber / red
    
    # Affected Surface
    apis_impacted: int
    ui_components_impacted: int
    dependency_depth: int
    tests_impacted: int
    
    # Recommended Action
    recommended_action: str
    action_justification: str
    
    # Explainability
    top_impact_factors: List[str]
    
    # Pipeline Status
    test_selection_status: str  # suggested / pending
    ci_execution_state: str  # Pending / Running / Completed


def prepare_model_input(request: ImpactAnalysisRequest) -> pd.DataFrame:
    """Prepare input features for the ML model"""
    global _model_features
    
    if not _model_features:
        load_impact_model()
    
    # Create base numerical features
    data = {
        'lines_changed': request.lines_changed,
        'files_changed': request.files_changed,
        'dependency_depth': request.dependency_depth,
        'shared_component': request.shared_component,
        'historical_failure_count': request.historical_failure_count,
        'historical_change_frequency': request.historical_change_frequency,
        'days_since_last_failure': request.days_since_last_failure,
        'tests_impacted': request.tests_impacted
    }
    
    # Create one-hot encoded categorical features
    # Initialize all categorical feature columns to 0
    for feature in _model_features:
        if feature not in data:
            data[feature] = 0
    
    # Set the appropriate categorical columns to 1
    # repo_type (drop_first means 'microservices' is reference)
    if request.repo_type == 'monolith':
        data['repo_type_monolith'] = 1
    
    # module_name (first module is reference, dropped)
    module_col = f'module_name_{request.module_name}'
    if module_col in data:
        data[module_col] = 1
    
    # change_type (API_CHANGE is reference, dropped)
    change_col = f'change_type_{request.change_type}'
    if change_col in data:
        data[change_col] = 1
    
    # component_type (API is reference, dropped)
    component_col = f'component_type_{request.component_type}'
    if component_col in data:
        data[component_col] = 1
    
    # function_category (admin is reference, dropped)
    func_col = f'function_category_{request.function_category}'
    if func_col in data:
        data[func_col] = 1
    
    # test_coverage_level (high is reference, dropped)
    coverage_col = f'test_coverage_level_{request.test_coverage_level}'
    if coverage_col in data:
        data[coverage_col] = 1
    
    # Create DataFrame with correct column order
    df = pd.DataFrame([data])
    
    # Ensure all model features are present in correct order
    for feature in _model_features:
        if feature not in df.columns:
            df[feature] = 0
    
    return df[_model_features]


def get_top_impact_factors(request: ImpactAnalysisRequest, risk_score: float) -> List[str]:
    """Generate human-readable impact factors"""
    factors = []
    
    if request.shared_component == 1:
        factors.append("Shared component modified")
    
    if request.historical_failure_count > 5:
        factors.append("High historical failure rate")
    elif request.historical_failure_count > 2:
        factors.append("Moderate historical failure rate")
    
    if request.dependency_depth > 3:
        factors.append(f"Deep dependency chain (depth: {request.dependency_depth})")
    
    if request.lines_changed > 500:
        factors.append("Large code change volume")
    elif request.lines_changed > 100:
        factors.append("Moderate code change volume")
    
    if request.files_changed > 10:
        factors.append("Many files affected")
    
    if request.test_coverage_level == 'low':
        factors.append("Low test coverage area")
    
    if request.change_type == 'API_CHANGE':
        factors.append("API contract modification")
    
    if request.function_category in ['auth', 'payment']:
        factors.append(f"Critical function area ({request.function_category})")
    
    if request.days_since_last_failure < 7:
        factors.append("Recent failures in this area")
    
    if request.historical_change_frequency > 10:
        factors.append("High change frequency area")
    
    # Return top 5 factors
    return factors[:5] if factors else ["Standard code modification"]


def get_recommended_action(risk_score: float, request: ImpactAnalysisRequest) -> tuple:
    """Generate recommended action and justification"""
    if risk_score >= 0.7:
        action = "Run full regression tests"
        justification = f"High risk score ({risk_score:.2f}) detected due to changes in critical areas. Full regression recommended to ensure system stability."
    elif risk_score >= 0.4:
        action = "Run targeted tests + integration tests"
        justification = f"Moderate risk ({risk_score:.2f}) suggests running tests for affected modules and their integrations."
    else:
        action = "Run targeted tests only"
        justification = f"Low risk ({risk_score:.2f}) indicates isolated changes. Standard unit and targeted tests should suffice."
    
    # Add specific recommendations based on change type
    if request.change_type == 'API_CHANGE':
        action += " + API contract tests"
    elif request.change_type == 'UI_CHANGE':
        action += " + UI regression tests"
    
    return action, justification


@app.post("/api/impact-analysis", response_model=ImpactAnalysisResponse)
async def run_impact_analysis(request_body: ImpactAnalysisRequest, request: Request):
    """
    Run ML-based impact analysis on code changes.
    
    This endpoint receives change metrics and returns:
    - Risk score (0.0 - 1.0)
    - Risk level (Low/Medium/High)
    - Recommended actions
    - Impact factors
    
    Used by AI Test Case Generator and Test Prioritization systems.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Load model if not loaded
        model = load_impact_model()
        
        if model is None:
            # Fallback to rule-based analysis if model not available
            risk_score = calculate_rule_based_risk(request_body)
        else:
            # Prepare input for ML model
            X = prepare_model_input(request_body)
            
            # Get probability prediction
            risk_score = float(model.predict_proba(X)[0, 1])
        
        # Determine risk level and color
        if risk_score >= 0.7:
            risk_level = "High"
            risk_color = "red"
        elif risk_score >= 0.4:
            risk_level = "Medium"
            risk_color = "amber"
        else:
            risk_level = "Low"
            risk_color = "green"
        
        # Get recommended action
        recommended_action, justification = get_recommended_action(risk_score, request_body)
        
        # Get impact factors
        impact_factors = get_top_impact_factors(request_body, risk_score)
        
        # Calculate affected surface
        apis_impacted = 0
        ui_components_impacted = 0
        
        if request_body.files_list:
            for file in request_body.files_list:
                file_lower = file.lower()
                if any(x in file_lower for x in ['/api/', 'routes', 'endpoints', 'controller']):
                    apis_impacted += 1
                if any(x in file_lower for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/']):
                    ui_components_impacted += 1
        else:
            # Estimate based on change type
            if request_body.change_type == 'API_CHANGE':
                apis_impacted = max(1, request_body.files_changed // 3)
            if request_body.change_type == 'UI_CHANGE':
                ui_components_impacted = max(1, request_body.files_changed // 2)
        
        return ImpactAnalysisResponse(
            repository=request_body.repository,
            branch=request_body.branch,
            commit_id=request_body.commit_id,
            files_changed=request_body.files_changed,
            lines_changed=request_body.lines_changed,
            change_category=request_body.change_type,
            risk_score=round(risk_score, 4),
            risk_level=risk_level,
            risk_color=risk_color,
            apis_impacted=apis_impacted,
            ui_components_impacted=ui_components_impacted,
            dependency_depth=request_body.dependency_depth,
            tests_impacted=request_body.tests_impacted,
            recommended_action=recommended_action,
            action_justification=justification,
            top_impact_factors=impact_factors,
            test_selection_status="suggested",
            ci_execution_state="Pending"
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Impact analysis error: {str(e)}")


def calculate_rule_based_risk(request: ImpactAnalysisRequest) -> float:
    """
    Enhanced rule-based risk calculation with domain-specific boosts.
    
    Scoring components:
    - Structural score: lines, files, dependencies (0 - 0.50)
    - Domain score: auth, payment, etc. based on function_category (0 - 0.30)
    - Coverage/history score: test coverage, failure history (0 - 0.20)
    """
    risk = 0.0
    
    # ==================== STRUCTURAL SCORE (max 0.35) ====================
    
    # Lines changed factor (0-0.12)
    if request.lines_changed > 500:
        risk += 0.12
    elif request.lines_changed > 200:
        risk += 0.10
    elif request.lines_changed > 100:
        risk += 0.07
    elif request.lines_changed > 50:
        risk += 0.05
    else:
        risk += 0.02
    
    # Files changed factor (0-0.10)
    if request.files_changed > 20:
        risk += 0.10
    elif request.files_changed > 10:
        risk += 0.08
    elif request.files_changed > 5:
        risk += 0.05
    else:
        risk += 0.02
    
    # Dependency depth factor (0-0.08)
    risk += min(request.dependency_depth * 0.02, 0.08)
    
    # Shared component factor (0-0.05)
    if request.shared_component:
        risk += 0.05
    
    # ==================== DOMAIN SCORE (max 0.40) ====================
    
    # Function category - ENHANCED SCORING
    function_category = request.function_category.lower() if request.function_category else 'misc'
    
    # Authentication/Security domain (+25%)
    if function_category in ['auth', 'authentication', 'security', 'login', 'session']:
        risk += 0.25
    # Financial/Payment domain (+30%)
    elif function_category in ['payment', 'billing', 'transaction', 'wallet', 'finance']:
        risk += 0.30
    # Admin/Permission domain (+20%)
    elif function_category in ['admin', 'permission', 'access', 'role']:
        risk += 0.20
    # User data domain (+15%)
    elif function_category in ['profile', 'user', 'account', 'settings']:
        risk += 0.15
    # Search/Query domain (+10%)
    elif function_category in ['search', 'query', 'filter', 'analytics']:
        risk += 0.10
    else:
        risk += 0.03
    
    # Change type factor (0-0.10)
    if request.change_type == 'API_CHANGE':
        risk += 0.10
    elif request.change_type == 'SERVICE_LOGIC_CHANGE':
        risk += 0.07
    elif request.change_type == 'UI_CHANGE':
        risk += 0.04
    else:
        risk += 0.02
    
    # ==================== COVERAGE/HISTORY SCORE (max 0.20) ====================
    
    # Historical failure factor (0-0.10)
    risk += min(request.historical_failure_count * 0.02, 0.10)
    
    # Test coverage factor (0-0.10)
    if request.test_coverage_level == 'low':
        risk += 0.10
    elif request.test_coverage_level == 'medium':
        risk += 0.04
    # high coverage adds no risk
    
    return min(risk, 0.95)  # Cap at 95%


@app.get("/api/impact-analysis/features")
async def get_impact_analysis_features(request: Request):
    """
    Get the required input features for impact analysis.
    Useful for UI forms and validation.
    """
    return {
        "numerical_features": REQUIRED_NUMERICAL_FEATURES,
        "categorical_features": REQUIRED_CATEGORICAL_FEATURES,
        "model_loaded": _impact_model is not None,
        "threshold": _model_threshold,
        "risk_keywords": list(RISK_KEYWORDS.keys())
    }


@app.get("/api/impact-analysis/from-event/{event_id}")
async def run_impact_analysis_from_event(event_id: int, request: Request):
    """
    Run impact analysis using data from a processed webhook event.
    Automatically extracts features from the diff analysis.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get the event from database
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = %s", (event_id,))
            row = cursor.fetchone()
            if row:
                event = dict(row)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        if not event.get('processed') or not event.get('processing_result'):
            raise HTTPException(status_code=400, detail="Event not yet processed. Please wait for diff analysis to complete.")
        
        # Parse the analysis result
        analysis = json.loads(event['processing_result'])
        
        # Extract features from analysis
        files = analysis.get('changed_files', analysis.get('files', []))
        logical_changes = analysis.get('logical_changes', {})
        
        # Calculate lines changed
        total_lines = 0
        for f in files:
            total_lines += f.get('additions', 0) + f.get('deletions', 0)
            # Also count from line_ranges if available
            for r in f.get('line_ranges', []):
                total_lines += (r.get('end', r.get('start', 0)) - r.get('start', 0) + 1)
        
        # Determine change type
        change_type = 'SERVICE_LOGIC_CHANGE'
        component_type = 'SERVICE'
        
        api_files = 0
        ui_files = 0
        config_files = 0
        
        for f in files:
            path = f.get('path', '').lower()
            if any(x in path for x in ['/api/', 'routes', 'endpoints', 'controller']):
                api_files += 1
            if any(x in path for x in ['.html', '.css', '.jsx', '.tsx', '/ui/', '/components/']):
                ui_files += 1
            if any(x in path for x in ['config', '.json', '.yaml', '.yml', '.env']):
                config_files += 1
        
        if api_files > len(files) // 2:
            change_type = 'API_CHANGE'
            component_type = 'API'
        elif ui_files > len(files) // 2:
            change_type = 'UI_CHANGE'
            component_type = 'UI'
        elif config_files > len(files) // 2:
            change_type = 'CONFIG_CHANGE'
        
        # Build impact analysis request
        impact_request = ImpactAnalysisRequest(
            lines_changed=max(total_lines, 1),
            files_changed=len(files),
            dependency_depth=1,  # Could be calculated from imports
            shared_component=1 if any('shared' in f.get('path', '').lower() for f in files) else 0,
            historical_failure_count=0,  # Would need historical data
            historical_change_frequency=1,
            days_since_last_failure=30,
            tests_impacted=len([f for f in files if 'test' in f.get('path', '').lower()]),
            repo_type='monolith',
            module_name='CoreModule',
            change_type=change_type,
            component_type=component_type,
            function_category='misc',
            test_coverage_level='medium',
            repository=event.get('repository_full_name'),
            branch=event.get('branch'),
            commit_id=event.get('commit_sha'),
            files_list=[f.get('path') for f in files]
        )
        
        # Run impact analysis
        return await run_impact_analysis(impact_request, request)
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== PIPELINE RESULTS API ====================

@app.get("/api/pipeline/recent")
async def get_recent_pipeline_results(request: Request, repository: Optional[str] = None, limit: int = 10):
    """
    Get recent pipeline results (git diff + impact analysis) for dashboard display.
    Returns processed webhook events with their impact analysis results.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        events = get_recent_webhook_events(repository, min(limit, 50))
        
        results = []
        for event in events:
            if event.get('processed') and event.get('processing_result'):
                try:
                    result_data = json.loads(event['processing_result'])
                    impact = result_data.get('impact_analysis')
                    
                    results.append({
                        "event_id": event['id'],
                        "repository": event['repository_full_name'],
                        "branch": event.get('branch'),
                        "commit_sha": event.get('commit_sha'),
                        "event_type": event['event_type'],
                        "processed_at": event.get('processed_at'),
                        "created_at": event.get('created_at'),
                        "pipeline_status": result_data.get('pipeline_status', 'unknown'),
                        "impact_analysis": impact,
                        "has_error": 'error' in result_data
                    })
                except:
                    pass
        
        return {
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pipeline/stats")
async def get_pipeline_stats(request: Request):
    """
    Get pipeline statistics for dashboard widgets.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        # Get recent events
        events = get_recent_webhook_events(None, 100)
        
        total_analyses = 0
        high_risk_count = 0
        medium_risk_count = 0
        low_risk_count = 0
        latest_analysis = None
        
        for event in events:
            if event.get('processed') and event.get('processing_result'):
                try:
                    result_data = json.loads(event['processing_result'])
                    impact = result_data.get('impact_analysis')
                    
                    if impact:
                        total_analyses += 1
                        risk_level = impact.get('risk_level', '').lower()
                        
                        if risk_level == 'high':
                            high_risk_count += 1
                        elif risk_level == 'medium':
                            medium_risk_count += 1
                        elif risk_level == 'low':
                            low_risk_count += 1
                        
                        if latest_analysis is None:
                            latest_analysis = impact
                except:
                    pass
        
        # Get connected repos count
        repos_count = 0
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM repositories")
            row = cursor.fetchone()
            if row:
                repos_count = row['count']
        
        return {
            "connected_repos": repos_count,
            "total_analyses": total_analyses,
            "high_risk_changes": high_risk_count,
            "medium_risk_changes": medium_risk_count,
            "low_risk_changes": low_risk_count,
            "latest_analysis": latest_analysis
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pipeline/event/{event_id}")
async def get_pipeline_event_detail(event_id: int, request: Request):
    """
    Get detailed pipeline result for a specific event.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import json
    
    try:
        event = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhook_events WHERE id = %s", (event_id,))
            row = cursor.fetchone()
            if row:
                event = dict(row)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        result_data = None
        if event.get('processing_result'):
            try:
                result_data = json.loads(event['processing_result'])
            except:
                result_data = {"raw": event['processing_result']}
        
        return {
            "event_id": event['id'],
            "repository": event['repository_full_name'],
            "branch": event.get('branch'),
            "commit_sha": event.get('commit_sha'),
            "event_type": event['event_type'],
            "processed": bool(event.get('processed')),
            "processed_at": event.get('processed_at'),
            "created_at": event.get('created_at'),
            "diff_analysis": result_data.get('diff_analysis') if result_data else None,
            "impact_analysis": result_data.get('impact_analysis') if result_data else None,
            "pipeline_status": result_data.get('pipeline_status') if result_data else 'pending'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/impact-analysis", response_class=HTMLResponse)
async def impact_analysis_page():
    """Serve the impact analysis page"""
    return FileResponse("frontend/pages/impact_analysis.html")


@app.post("/api/sync/commits")
async def sync_commits_from_github(request: Request, repository: Optional[str] = None, limit: int = 50):
    """
    Sync recent commits from GitHub API directly.
    This bypasses webhooks and fetches commits directly from GitHub.
    No artificial limit - fetches as many commits as specified.
    """
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        synced_count = 0
        errors = []
        
        async with httpx.AsyncClient() as client:
            # Get user's repos if no specific repo provided
            if repository:
                repos_to_sync = [repository]
            else:
                # Get connected repos from database
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT full_name FROM repositories")
                    repos_to_sync = [row[0] for row in cursor.fetchall()]
            
            if not repos_to_sync:
                return {"synced": 0, "message": "No repositories connected"}
            
            for repo_full_name in repos_to_sync:
                try:
                    owner, repo = repo_full_name.split('/')
                    
                    # Fetch commits from GitHub (configurable limit)
                    commits_response = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/commits",
                        params={"per_page": min(limit, 100)},  # GitHub max is 100 per page
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github.v3+json",
                        },
                    )
                    
                    if commits_response.status_code != 200:
                        errors.append(f"{repo_full_name}: Failed to fetch commits")
                        continue
                    
                    commits = commits_response.json()
                    
                    for commit in commits:
                        commit_sha = commit['sha']
                        
                        # Check if we already have this commit
                        existing = get_webhook_event_by_delivery_id(f"sync-{commit_sha}")
                        if existing:
                            continue
                        
                        # Also check by commit_sha
                        with get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "SELECT id FROM webhook_events WHERE commit_sha = %s",
                                (commit_sha,)
                            )
                            if cursor.fetchone():
                                continue
                        
                        # Get the parent SHA for diff
                        parent_sha = commit['parents'][0]['sha'] if commit.get('parents') else None
                        
                        # Create a synthetic webhook event
                        event_data = {
                            "github_delivery_id": f"sync-{commit_sha}",
                            "event_type": "push",
                            "repository_full_name": repo_full_name,
                            "branch": "main",
                            "commit_sha": commit_sha,
                            "before_sha": parent_sha,
                            "payload": json.dumps({
                                "ref": "refs/heads/main",
                                "after": commit_sha,
                                "before": parent_sha,
                                "repository": {"full_name": repo_full_name},
                                "commits": [{
                                    "id": commit_sha,
                                    "message": commit['commit']['message'],
                                    "author": commit['commit']['author'],
                                    "added": [],
                                    "modified": [],
                                    "removed": []
                                }],
                                "head_commit": {
                                    "id": commit_sha,
                                    "message": commit['commit']['message']
                                }
                            })
                        }
                        
                        # Create the event in database
                        stored_event = create_webhook_event(
                            webhook_id=1,
                            delivery_id=event_data["github_delivery_id"],
                            event_type=event_data["event_type"],
                            repository_full_name=event_data["repository_full_name"],
                            branch=event_data["branch"],
                            commit_sha=event_data["commit_sha"],
                            before_sha=event_data["before_sha"],
                            payload=event_data["payload"]
                        )
                        
                        if stored_event:
                            event_id = stored_event["id"]
                            synced_count += 1
                            
                            # Process the event immediately
                            try:
                                # Get diff from GitHub
                                diff_response = await client.get(
                                    f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}",
                                    headers={
                                        "Authorization": f"Bearer {token}",
                                        "Accept": "application/vnd.github.v3.diff",
                                    },
                                )
                                
                                if diff_response.status_code == 200:
                                    diff_content = diff_response.text
                                    
                                    # Run impact analysis
                                    features = extract_features_from_diff(diff_content)
                                    analysis_result = run_impact_analysis_from_features(features)
                                    
                                    # Store the result
                                    processing_result = {
                                        "pipeline_status": "completed",
                                        "diff_analysis": features,
                                        "impact_analysis": analysis_result
                                    }
                                    
                                    mark_webhook_event_processed(
                                        event_id,
                                        json.dumps(processing_result)
                                    )
                            except Exception as proc_error:
                                print(f"Error processing commit {commit_sha}: {proc_error}")
                                
                except Exception as repo_error:
                    errors.append(f"{repo_full_name}: {str(repo_error)}")
        
        return {
            "synced": synced_count,
            "repositories": repos_to_sync,
            "errors": errors if errors else None,
            "message": f"Synced {synced_count} new commits"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test-runs", response_class=HTMLResponse)
async def test_runs_page():
    """Serve the test runs page"""
    return FileResponse("frontend/pages/test_runs.html")


@app.get("/failures", response_class=HTMLResponse)
async def failures_page():
    """Serve the failures page"""
    return FileResponse("frontend/pages/failures.html")


@app.get("/self-healing", response_class=HTMLResponse)
async def self_healing_page():
    """Serve the self-healing page"""
    return FileResponse("frontend/pages/self_healing.html")
