from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from pydantic import BaseModel
from typing import Optional
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
    get_user_settings, update_user_settings
)

# Import GitHub API module
from backend.api.git_repo import GitHubAPI

# Import Repository Intelligence routes (Phase 1)
from backend.api.repo_routes import router as repo_router

# Import Webhook routes for auto-fetch/pull
from backend.api.webhook_routes import router as webhook_router

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

# Include Repository Intelligence router (Phase 1)
app.include_router(repo_router)

# Include Webhook router for auto-fetch/pull
app.include_router(webhook_router)


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
@app.get("/auth/github/login")
async def github_login(setup: bool = False, force_login: bool = False):
    """Redirect user to GitHub OAuth authorization page with CSRF protection
    
    Args:
        setup: Whether this is from the setup flow
        force_login: If True, forces GitHub to show login screen (for account switching)
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
    
    # Generate CSRF state token with setup flag
    state = generate_csrf_state()
    # Store setup flag in state (format: state_token:setup_flag)
    state_with_flag = f"{state}:{'1' if setup else '0'}"
    csrf_states[state_with_flag] = csrf_states.pop(state)
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=user%20repo"
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
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
    
    # Generate CSRF state token with setup flag
    state = generate_csrf_state()
    # Store setup flag in state (format: state_token:setup_flag)
    state_with_flag = f"{state}:{'1' if setup else '0'}"
    csrf_states[state_with_flag] = csrf_states.pop(state)
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=user%20repo"
        f"&state={state_with_flag}"
        f"&prompt=select_account"  # Force account picker to appear
    )
    
    return {"url": github_auth_url}


@app.get("/auth/github/callback")
async def github_callback(code: str = None, state: str = None, error: str = None):
    """Handle GitHub OAuth callback with CSRF validation"""
    # Handle OAuth errors (e.g., user cancelled login) - redirect back to dashboard
    if error:
        # User cancelled or denied access, redirect to dashboard gracefully
        return RedirectResponse(url="/dashboard")
    
    # Parse state to get setup flag
    is_setup = False
    if state and ':' in state:
        state_parts = state.rsplit(':', 1)
        is_setup = state_parts[1] == '1'
    
    # Validate CSRF state
    if not validate_csrf_state(state):
        raise HTTPException(status_code=403, detail="Invalid or expired state parameter (CSRF protection)")
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    
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
        
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to obtain access token")
        
        token_data = token_response.json()
        
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description", token_data["error"]))
        
        access_token = token_data.get("access_token")
        
        # Fetch user info from GitHub
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
    
    # Check if user exists in database
    existing_user = get_user_by_github_id(user_data.get('id'))
    
    # Create session with token metadata
    token_issued_at = int(time.time())
    
    # Directly redirect to the Electron app via custom protocol
    setup_param = "true" if is_setup else "false"
    deep_link_url = f"ettax://auth?token={access_token}&setup={setup_param}"
    
    # Use RedirectResponse to immediately open the app
    response = RedirectResponse(url=deep_link_url, status_code=302)
    
    # Also set cookies for web fallback (if user opens in browser instead)
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