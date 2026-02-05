"""
HIGH RISK - Payment Gateway and Core Shared Components
This should trigger HIGH risk (70-90)
CRITICAL: Modifications to payment processing and shared infrastructure
"""

import json
import hashlib
import hmac
import secrets
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from abc import ABC, abstractmethod


# ============================================================================
# SHARED CORE COMPONENTS - HIGH IMPACT
# ============================================================================

class BaseController(ABC):
    """Base controller for all API endpoints - SHARED COMPONENT."""
    
    def __init__(self, request, response, auth_service):
        self.request = request
        self.response = response
        self.auth = auth_service
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    def handle(self) -> Dict[str, Any]:
        """Handle the request."""
        pass
    
    def validate_auth(self) -> Optional[str]:
        """Validate authentication token."""
        token = self.request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            raise AuthenticationError("Missing authentication token")
        user_id = self.auth.validate_token(token)
        if not user_id:
            raise AuthenticationError("Invalid or expired token")
        return user_id
    
    def json_response(self, data: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
        """Return JSON response."""
        return {"status": status, "data": data}
    
    def error_response(self, message: str, status: int = 400) -> Dict[str, Any]:
        """Return error response."""
        return {"status": status, "error": message}


class BaseService(ABC):
    """Base service class - SHARED COMPONENT."""
    
    def __init__(self, db, cache, event_bus):
        self.db = db
        self.cache = cache
        self.event_bus = event_bus
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit event to event bus."""
        self.event_bus.publish(event_type, {
            "timestamp": datetime.now().isoformat(),
            "data": data
        })
    
    def get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        value = self.cache.get(key)
        return json.loads(value) if value else None
    
    def set_cached(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in cache."""
        self.cache.set(key, json.dumps(value), ex=ttl)


class DatabaseManager:
    """Core database manager - CRITICAL SHARED COMPONENT."""
    
    def __init__(self, connection_string: str, pool_size: int = 10):
        self.connection_string = connection_string
        self.pool_size = pool_size
        self._pool = []
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Initialize connection pool."""
        for _ in range(self.pool_size):
            self._pool.append(self._create_connection())
    
    def _create_connection(self):
        """Create new database connection."""
        # Simulated connection
        return {"connected": True, "created_at": datetime.now()}
    
    def execute(self, query: str, params: Dict = None) -> Any:
        """Execute database query."""
        conn = self._get_connection()
        try:
            self.logger.debug(f"Executing: {query}")
            # Execute query
            return {"rows_affected": 1}
        finally:
            self._return_connection(conn)
    
    def _get_connection(self):
        """Get connection from pool."""
        if not self._pool:
            return self._create_connection()
        return self._pool.pop()
    
    def _return_connection(self, conn) -> None:
        """Return connection to pool."""
        if len(self._pool) < self.pool_size:
            self._pool.append(conn)


# ============================================================================
# PAYMENT PROCESSING - CRITICAL HIGH RISK
# ============================================================================

class PaymentStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentError(Exception):
    """Payment processing error."""
    pass


class AuthenticationError(Exception):
    """Authentication error."""
    pass


class PaymentGateway:
    """
    CRITICAL: Main payment gateway handler.
    Processes all financial transactions.
    """
    
    def __init__(self, api_key: str, secret_key: str, environment: str = "production"):
        self.api_key = api_key
        self.secret_key = secret_key
        self.environment = environment
        self.base_url = self._get_base_url()
        self.logger = logging.getLogger("PaymentGateway")
    
    def _get_base_url(self) -> str:
        """Get API base URL based on environment."""
        urls = {
            "production": "https://api.payment-provider.com/v1",
            "sandbox": "https://sandbox.payment-provider.com/v1",
            "development": "http://localhost:8080/v1"
        }
        return urls.get(self.environment, urls["sandbox"])
    
    def process_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_method: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a payment transaction.
        CRITICAL: Handles real money transactions.
        """
        self.logger.info(f"Processing payment: {amount} {currency}")
        
        # Validate amount
        if amount <= 0:
            raise PaymentError("Invalid payment amount")
        
        # Create transaction record
        transaction_id = self._generate_transaction_id()
        
        try:
            # Prepare payment request
            payload = {
                "transaction_id": transaction_id,
                "amount": str(amount),
                "currency": currency.upper(),
                "payment_method": payment_method,
                "metadata": metadata or {},
                "timestamp": datetime.now().isoformat()
            }
            
            # Sign request
            signature = self._sign_request(payload)
            
            # Process with payment provider
            result = self._call_payment_api("/charges", payload, signature)
            
            if result.get("status") == "success":
                return {
                    "transaction_id": transaction_id,
                    "status": PaymentStatus.COMPLETED.value,
                    "provider_reference": result.get("reference"),
                    "amount": amount,
                    "currency": currency,
                    "processed_at": datetime.now().isoformat()
                }
            else:
                raise PaymentError(f"Payment failed: {result.get('error')}")
                
        except Exception as e:
            self.logger.error(f"Payment processing error: {e}")
            return {
                "transaction_id": transaction_id,
                "status": PaymentStatus.FAILED.value,
                "error": str(e)
            }
    
    def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[Decimal] = None,
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        Process a refund for a previous transaction.
        CRITICAL: Returns money to customer.
        """
        self.logger.info(f"Processing refund for: {transaction_id}")
        
        payload = {
            "original_transaction_id": transaction_id,
            "refund_amount": str(amount) if amount else "full",
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        
        signature = self._sign_request(payload)
        result = self._call_payment_api("/refunds", payload, signature)
        
        return {
            "refund_id": self._generate_transaction_id(),
            "original_transaction_id": transaction_id,
            "status": PaymentStatus.REFUNDED.value if result.get("status") == "success" else PaymentStatus.FAILED.value,
            "processed_at": datetime.now().isoformat()
        }
    
    def _generate_transaction_id(self) -> str:
        """Generate unique transaction ID."""
        return f"txn_{secrets.token_hex(16)}"
    
    def _sign_request(self, payload: Dict[str, Any]) -> str:
        """Sign API request with HMAC."""
        message = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _call_payment_api(self, endpoint: str, payload: Dict, signature: str) -> Dict[str, Any]:
        """Call payment provider API."""
        # Simulated API call
        return {"status": "success", "reference": secrets.token_hex(8)}


class TransactionManager:
    """
    CRITICAL: Manages all financial transactions.
    Shared component used by multiple services.
    """
    
    def __init__(self, db: DatabaseManager, payment_gateway: PaymentGateway):
        self.db = db
        self.gateway = payment_gateway
        self.logger = logging.getLogger("TransactionManager")
    
    def create_transaction(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        transaction_type: str,
        payment_method: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create and process a new transaction."""
        
        # Record transaction intent
        transaction = {
            "id": secrets.token_hex(16),
            "user_id": user_id,
            "amount": str(amount),
            "currency": currency,
            "type": transaction_type,
            "status": PaymentStatus.PENDING.value,
            "created_at": datetime.now().isoformat()
        }
        
        self.db.execute(
            "INSERT INTO transactions (id, user_id, amount, currency, type, status, created_at) VALUES (:id, :user_id, :amount, :currency, :type, :status, :created_at)",
            transaction
        )
        
        # Process payment
        result = self.gateway.process_payment(amount, currency, payment_method)
        
        # Update transaction status
        transaction["status"] = result["status"]
        transaction["provider_reference"] = result.get("provider_reference")
        transaction["processed_at"] = result.get("processed_at")
        
        self.db.execute(
            "UPDATE transactions SET status = :status, provider_reference = :provider_reference, processed_at = :processed_at WHERE id = :id",
            transaction
        )
        
        return transaction
    
    def get_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get transaction by ID."""
        return self.db.execute(
            "SELECT * FROM transactions WHERE id = :id",
            {"id": transaction_id}
        )
    
    def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get transactions for a user."""
        return self.db.execute(
            "SELECT * FROM transactions WHERE user_id = :user_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            {"user_id": user_id, "limit": limit, "offset": offset}
        )


class BillingService(BaseService):
    """
    CRITICAL: Handles subscription billing and invoicing.
    """
    
    def __init__(self, db, cache, event_bus, transaction_manager: TransactionManager):
        super().__init__(db, cache, event_bus)
        self.transaction_manager = transaction_manager
    
    def create_subscription(
        self,
        user_id: str,
        plan_id: str,
        payment_method: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new subscription."""
        plan = self._get_plan(plan_id)
        if not plan:
            raise ValueError(f"Invalid plan: {plan_id}")
        
        # Process initial payment
        transaction = self.transaction_manager.create_transaction(
            user_id=user_id,
            amount=Decimal(plan["price"]),
            currency=plan["currency"],
            transaction_type="subscription",
            payment_method=payment_method
        )
        
        if transaction["status"] != PaymentStatus.COMPLETED.value:
            raise PaymentError("Subscription payment failed")
        
        # Create subscription record
        subscription = {
            "id": secrets.token_hex(16),
            "user_id": user_id,
            "plan_id": plan_id,
            "status": "active",
            "current_period_start": datetime.now().isoformat(),
            "current_period_end": (datetime.now() + timedelta(days=30)).isoformat(),
            "created_at": datetime.now().isoformat()
        }
        
        self.db.execute("INSERT INTO subscriptions ...", subscription)
        self.emit_event("subscription.created", subscription)
        
        return subscription
    
    def cancel_subscription(self, subscription_id: str, reason: str = "") -> Dict[str, Any]:
        """Cancel a subscription."""
        self.db.execute(
            "UPDATE subscriptions SET status = 'cancelled', cancelled_at = :cancelled_at, cancellation_reason = :reason WHERE id = :id",
            {"id": subscription_id, "cancelled_at": datetime.now().isoformat(), "reason": reason}
        )
        self.emit_event("subscription.cancelled", {"id": subscription_id, "reason": reason})
        return {"id": subscription_id, "status": "cancelled"}
    
    def _get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get subscription plan details."""
        plans = {
            "basic": {"id": "basic", "price": "9.99", "currency": "USD"},
            "pro": {"id": "pro", "price": "29.99", "currency": "USD"},
            "enterprise": {"id": "enterprise", "price": "99.99", "currency": "USD"}
        }
        return plans.get(plan_id)


class InvoiceGenerator:
    """Generate invoices for transactions and subscriptions."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def generate_invoice(
        self,
        user_id: str,
        items: List[Dict[str, Any]],
        due_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Generate a new invoice."""
        invoice_id = f"INV-{secrets.token_hex(8).upper()}"
        
        subtotal = sum(Decimal(item["amount"]) for item in items)
        tax = subtotal * Decimal("0.1")  # 10% tax
        total = subtotal + tax
        
        invoice = {
            "id": invoice_id,
            "user_id": user_id,
            "items": items,
            "subtotal": str(subtotal),
            "tax": str(tax),
            "total": str(total),
            "currency": "USD",
            "status": "pending",
            "due_date": (due_date or datetime.now() + timedelta(days=30)).isoformat(),
            "created_at": datetime.now().isoformat()
        }
        
        self.db.execute("INSERT INTO invoices ...", invoice)
        return invoice


class WalletService(BaseService):
    """
    CRITICAL: Manages user wallet and balance.
    """
    
    def get_balance(self, user_id: str) -> Dict[str, Decimal]:
        """Get user wallet balance."""
        cache_key = f"wallet:{user_id}"
        cached = self.get_cached(cache_key)
        if cached:
            return cached
        
        balance = self.db.execute(
            "SELECT currency, balance FROM wallets WHERE user_id = :user_id",
            {"user_id": user_id}
        )
        
        result = {"USD": Decimal("0"), "EUR": Decimal("0")}
        self.set_cached(cache_key, result, ttl=300)
        return result
    
    def add_funds(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        source: str
    ) -> Dict[str, Any]:
        """Add funds to user wallet."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        self.db.execute(
            "UPDATE wallets SET balance = balance + :amount WHERE user_id = :user_id AND currency = :currency",
            {"user_id": user_id, "amount": str(amount), "currency": currency}
        )
        
        # Record transaction
        self.db.execute(
            "INSERT INTO wallet_transactions (user_id, amount, currency, type, source, created_at) VALUES (:user_id, :amount, :currency, 'credit', :source, :created_at)",
            {"user_id": user_id, "amount": str(amount), "currency": currency, "source": source, "created_at": datetime.now().isoformat()}
        )
        
        # Invalidate cache
        self.cache.delete(f"wallet:{user_id}")
        
        return {"user_id": user_id, "amount_added": amount, "currency": currency}
    
    def withdraw_funds(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        destination: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Withdraw funds from user wallet."""
        balance = self.get_balance(user_id)
        
        if balance.get(currency, Decimal("0")) < amount:
            raise ValueError("Insufficient balance")
        
        self.db.execute(
            "UPDATE wallets SET balance = balance - :amount WHERE user_id = :user_id AND currency = :currency",
            {"user_id": user_id, "amount": str(amount), "currency": currency}
        )
        
        # Record transaction
        self.db.execute(
            "INSERT INTO wallet_transactions (user_id, amount, currency, type, destination, created_at) VALUES (:user_id, :amount, :currency, 'debit', :destination, :created_at)",
            {"user_id": user_id, "amount": str(amount), "currency": currency, "destination": json.dumps(destination), "created_at": datetime.now().isoformat()}
        )
        
        # Invalidate cache
        self.cache.delete(f"wallet:{user_id}")
        
        return {"user_id": user_id, "amount_withdrawn": amount, "currency": currency, "status": "processing"}


# ============================================================================
# SECURITY COMPONENTS - CRITICAL
# ============================================================================

class SecurityManager:
    """
    CRITICAL: Handles encryption, hashing, and security operations.
    Shared across all services.
    """
    
    def __init__(self, encryption_key: bytes):
        self.encryption_key = encryption_key
    
    def hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data using SHA-256."""
        return hashlib.sha256(data.encode()).hexdigest()
    
    def generate_secure_token(self, length: int = 32) -> str:
        """Generate cryptographically secure token."""
        return secrets.token_urlsafe(length)
    
    def verify_signature(self, payload: str, signature: str, secret: str) -> bool:
        """Verify HMAC signature."""
        expected = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    
    def mask_card_number(self, card_number: str) -> str:
        """Mask credit card number for display."""
        if len(card_number) < 4:
            return "****"
        return f"****-****-****-{card_number[-4:]}"
    
    def mask_email(self, email: str) -> str:
        """Mask email for privacy."""
        parts = email.split("@")
        if len(parts) != 2:
            return "***@***"
        username = parts[0]
        domain = parts[1]
        masked_username = username[0] + "***" + username[-1] if len(username) > 2 else "***"
        return f"{masked_username}@{domain}"
