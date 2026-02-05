"""
SMALL CHANGE - This should trigger LOW risk (10-30)
Just a simple utility function addition
"""

def format_date(date_str):
    """Format a date string."""
    return date_str.strip()

def validate_email(email):
    """Basic email validation."""
    return "@" in email and "." in email
