"""
MEDIUM RISK - API Changes with multiple service modifications
This should trigger MEDIUM risk (40-60)
"""

import json
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta


class UserService:
    """Service for managing user operations."""
    
    def __init__(self, db_connection, cache_client):
        self.db = db_connection
        self.cache = cache_client
        self.session_timeout = 3600
    
    def create_user(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """Create a new user account."""
        hashed_password = self._hash_password(password)
        user_data = {
            "username": username,
            "email": email,
            "password": hashed_password,
            "created_at": datetime.now().isoformat(),
            "is_active": True
        }
        user_id = self.db.insert("users", user_data)
        self._invalidate_cache(f"user:{user_id}")
        return {"id": user_id, **user_data}
    
    def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user credentials."""
        user = self.db.find_one("users", {"email": email})
        if not user:
            return None
        if not self._verify_password(password, user["password"]):
            return None
        token = self._generate_token(user["id"])
        return {"user": user, "token": token}
    
    def update_profile(self, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile information."""
        allowed_fields = ["username", "email", "bio", "avatar_url"]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        update_data["updated_at"] = datetime.now().isoformat()
        self.db.update("users", {"id": user_id}, update_data)
        self._invalidate_cache(f"user:{user_id}")
        return self.get_user(user_id)
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID with caching."""
        cache_key = f"user:{user_id}"
        cached = self.cache.get(cache_key)
        if cached:
            return json.loads(cached)
        user = self.db.find_one("users", {"id": user_id})
        if user:
            self.cache.set(cache_key, json.dumps(user), ex=3600)
        return user
    
    def delete_user(self, user_id: str) -> bool:
        """Soft delete a user account."""
        self.db.update("users", {"id": user_id}, {
            "is_active": False,
            "deleted_at": datetime.now().isoformat()
        })
        self._invalidate_cache(f"user:{user_id}")
        return True
    
    def list_users(self, page: int = 1, limit: int = 20) -> List[Dict[str, Any]]:
        """List users with pagination."""
        offset = (page - 1) * limit
        return self.db.find("users", {"is_active": True}, limit=limit, offset=offset)
    
    def _hash_password(self, password: str) -> str:
        """Hash password using SHA256."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash."""
        return self._hash_password(password) == hashed
    
    def _generate_token(self, user_id: str) -> str:
        """Generate session token."""
        data = f"{user_id}:{datetime.now().timestamp()}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _invalidate_cache(self, key: str) -> None:
        """Invalidate cache entry."""
        self.cache.delete(key)


class AuthService:
    """Authentication and authorization service."""
    
    def __init__(self, user_service: UserService, token_store):
        self.user_service = user_service
        self.token_store = token_store
    
    def login(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Process user login."""
        result = self.user_service.authenticate(email, password)
        if result:
            self.token_store.set(result["token"], result["user"]["id"], ex=86400)
        return result
    
    def logout(self, token: str) -> bool:
        """Process user logout."""
        self.token_store.delete(token)
        return True
    
    def validate_token(self, token: str) -> Optional[str]:
        """Validate session token."""
        return self.token_store.get(token)
    
    def refresh_token(self, old_token: str) -> Optional[str]:
        """Refresh an existing token."""
        user_id = self.validate_token(old_token)
        if not user_id:
            return None
        self.logout(old_token)
        new_token = hashlib.sha256(f"{user_id}:{datetime.now().timestamp()}".encode()).hexdigest()
        self.token_store.set(new_token, user_id, ex=86400)
        return new_token
