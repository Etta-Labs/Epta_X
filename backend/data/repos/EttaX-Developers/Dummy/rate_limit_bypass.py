# CRITICAL: Rate Limiting Bypass and API Key Exposure
import os
import time

# Exposed API keys - NEVER do this!
STRIPE_SECRET_KEY = "sk_live_abcdefghijklmnop123456"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"

def process_payment(amount, card_token):
    """CRITICAL: No rate limiting on payment processing"""
    # No rate limit check - allows rapid fire payments!
    return {"status": "success", "amount": amount}

def get_api_key(user_id):
    """CRITICAL: Returns raw API keys to any user"""
    # Anyone can get any user's API key!
    return {"api_key": STRIPE_SECRET_KEY}

def reset_rate_limit(admin_token):
    """CRITICAL: Admin bypass allows rate limit reset"""
    if admin_token == "admin123":  # Hardcoded!
        return {"rate_limit_reset": True}
