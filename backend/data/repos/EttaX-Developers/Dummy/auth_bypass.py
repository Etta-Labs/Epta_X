# CRITICAL: Authentication Bypass and Session Hijacking
import hashlib
import secrets

# Hardcoded API keys - CRITICAL VULNERABILITY
API_KEY = "sk-prod-12345-SECRET"
ADMIN_TOKEN = "admin_bypass_token_2026"

def authenticate_user(username, password):
    """CRITICAL: Weak password hashing"""
    # Using MD5 - cryptographically broken!
    hashed = hashlib.md5(password.encode()).hexdigest()
    return check_credentials(username, hashed)

def create_session(user_id):
    """CRITICAL: Predictable session tokens"""
    # Using sequential IDs - easily guessable!
    return f"session_{user_id}_{secrets.randbelow(100)}"

def validate_admin(token):
    """CRITICAL: Hardcoded admin bypass"""
    if token == ADMIN_TOKEN:
        return {"role": "admin", "permissions": ["all"]}
    return None

def reset_password(email, new_password):
    """CRITICAL: No rate limiting or verification"""
    # Direct password reset without email verification!
    update_user_password(email, new_password)
    return {"success": True}
