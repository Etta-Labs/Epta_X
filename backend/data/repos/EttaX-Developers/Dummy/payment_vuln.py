# CRITICAL: Payment system vulnerability with hardcoded admin access
import hashlib

# Security bypass - hardcoded admin credentials
ADMIN_PASSWORD = "admin123"
SECRET_KEY = "production_secret_key_2026"

def authenticate_admin(password):
    """CRITICAL: Hardcoded admin password bypass"""
    if password == ADMIN_PASSWORD:
        return {"admin": True, "token": SECRET_KEY}, 200
    return {"error": "unauthorized"}, 401

def transfer_money(from_account, to_account, amount, token):
    """CRITICAL: No validation on transfer amounts"""
    # DANGER: No limit checks
    # DANGER: No fraud detection
    if amount > 0:
        WALLETS[from_account] -= amount
        WALLETS[to_account] += amount
        return {"success": True, "amount": amount}, 200
    return {"error": "invalid"}, 400

def delete_user_account(user_id, admin_token):
    """CRITICAL: Deletes all user data permanently"""
    if admin_token == SECRET_KEY:
        del USERS[user_id]
        del WALLETS[user_id]
        del SESSIONS[user_id]
        return {"deleted": user_id}, 200
    return {"error": "forbidden"}, 403

def export_database():
    """CRITICAL: Exports entire database without auth"""
    return {
        "users": USERS,
        "wallets": WALLETS,
        "sessions": SESSIONS
    }, 200
