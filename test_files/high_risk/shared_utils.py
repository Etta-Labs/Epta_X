"""
Shared utility functions used across all services.
HIGH RISK - Changes here affect multiple components.
"""

import re
import hashlib
from typing import Any, Dict, List, Optional
from datetime import datetime


class ValidationUtils:
    """Common validation utilities."""
    
    EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    PHONE_REGEX = re.compile(r'^\+?1?\d{9,15}$')
    
    @classmethod
    def validate_email(cls, email: str) -> bool:
        """Validate email format."""
        return bool(cls.EMAIL_REGEX.match(email))
    
    @classmethod
    def validate_phone(cls, phone: str) -> bool:
        """Validate phone number format."""
        return bool(cls.PHONE_REGEX.match(phone))
    
    @classmethod
    def validate_password_strength(cls, password: str) -> Dict[str, Any]:
        """Check password strength."""
        checks = {
            "min_length": len(password) >= 8,
            "has_uppercase": bool(re.search(r'[A-Z]', password)),
            "has_lowercase": bool(re.search(r'[a-z]', password)),
            "has_digit": bool(re.search(r'\d', password)),
            "has_special": bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
        }
        checks["is_strong"] = all(checks.values())
        return checks


class CryptoUtils:
    """Cryptographic utilities - CRITICAL SHARED."""
    
    @staticmethod
    def hash_sha256(data: str) -> str:
        """Generate SHA-256 hash."""
        return hashlib.sha256(data.encode()).hexdigest()
    
    @staticmethod
    def hash_sha512(data: str) -> str:
        """Generate SHA-512 hash."""
        return hashlib.sha512(data.encode()).hexdigest()
    
    @staticmethod
    def generate_checksum(data: bytes) -> str:
        """Generate MD5 checksum for data integrity."""
        return hashlib.md5(data).hexdigest()


class DateTimeUtils:
    """Date and time utilities."""
    
    @staticmethod
    def now_iso() -> str:
        """Get current datetime in ISO format."""
        return datetime.now().isoformat()
    
    @staticmethod
    def parse_iso(date_str: str) -> datetime:
        """Parse ISO format datetime string."""
        return datetime.fromisoformat(date_str)
    
    @staticmethod
    def format_display(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Format datetime for display."""
        return dt.strftime(fmt)


class StringUtils:
    """String manipulation utilities."""
    
    @staticmethod
    def truncate(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate string to max length."""
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def slugify(text: str) -> str:
        """Convert text to URL-friendly slug."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '-', text)
        return text
    
    @staticmethod
    def mask_sensitive(text: str, visible_chars: int = 4) -> str:
        """Mask sensitive string data."""
        if len(text) <= visible_chars:
            return '*' * len(text)
        return '*' * (len(text) - visible_chars) + text[-visible_chars:]
