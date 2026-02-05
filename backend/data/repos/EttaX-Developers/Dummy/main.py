

from datetime import datetime, timedelta
import hashlib
import uuid

# ---------------- MOCK DATABASE ----------------
USERS = {}
SESSIONS = {}
WALLETS = {}

# ---------------- HELPERS ----------------
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return str(uuid.uuid4())

def now():
    return datetime.utcnow()

# ---------------- AUTH MODULE ----------------

def register(username: str, password: str, initial_balance=0):
    if not username or not password:
        return {"error": "missing_fields"}, 400

    if username in USERS:
        return {"error": "user_exists"}, 409

    if len(password) < 6:
        return {"error": "weak_password"}, 400

    USERS[username] = hash_password(password)
    WALLETS[username] = initial_balance

    return {"message": "registered"}, 201


def login(username: str, password: str):
    if username not in USERS:
        return {"error": "invalid_credentials"}, 401

    if USERS[username] != hash_password(password):
        return {"error": "invalid_credentials"}, 401

    token = generate_token()
    SESSIONS[token] = {
        "username": username,
        "expires": now() + timedelta(minutes=30)
    }

    return {"token": token}, 200


def authenticate(token: str):
    session = SESSIONS.get(token)
    if not session:
        return None, {"error": "unauthorized"}, 401

    if session["expires"] < now():
        del SESSIONS[token]
        return None, {"error": "session_expired"}, 401

    return session["username"], None, 200


# ---------------- WALLET MODULE ----------------

def get_balance(token: str):
    user, err, code = authenticate(token)
    if err:
        return err, code

    return {"balance": WALLETS[user]}, 200


def deposit(token: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    WALLETS[user] += amount
    return {"balance": WALLETS[user]}, 200


def transfer(token: str, to_user: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if to_user not in USERS:
        return {"error": "receiver_not_found"}, 404

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    if WALLETS[user] < amount:
        return {"error": "insufficient_funds"}, 403

    WALLETS[user] -= amount
    WALLETS[to_user] += amount

    return {"balance": WALLETS[user]}, 200



from datetime import datetime, timedelta
import hashlib
import uuid

# ---------------- MOCK DATABASE ----------------
USERS = {}
SESSIONS = {}
WALLETS = {}

# ---------------- HELPERS ----------------
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return str(uuid.uuid4())

def now():
    return datetime.utcnow()

# ---------------- AUTH MODULE ----------------

def register(username: str, password: str, initial_balance=0):
    if not username or not password:
        return {"error": "missing_fields"}, 400

    if username in USERS:
        return {"error": "user_exists"}, 409

    if len(password) < 6:
        return {"error": "weak_password"}, 400

    USERS[username] = hash_password(password)
    WALLETS[username] = initial_balance

    return {"message": "registered"}, 201


def login(username: str, password: str):
    if username not in USERS:
        return {"error": "invalid_credentials"}, 401

    if USERS[username] != hash_password(password):
        return {"error": "invalid_credentials"}, 401

    token = generate_token()
    SESSIONS[token] = {
        "username": username,
        "expires": now() + timedelta(minutes=30)
    }

    return {"token": token}, 200


def authenticate(token: str):
    session = SESSIONS.get(token)
    if not session:
        return None, {"error": "unauthorized"}, 401

    if session["expires"] < now():
        del SESSIONS[token]
        return None, {"error": "session_expired"}, 401

    return session["username"], None, 200


# ---------------- WALLET MODULE ----------------

def get_balance(token: str):
    user, err, code = authenticate(token)
    if err:
        return err, code

    return {"balance": WALLETS[user]}, 200


def deposit(token: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    WALLETS[user] += amount
    return {"balance": WALLETS[user]}, 200


def transfer(token: str, to_user: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if to_user not in USERS:
        return {"error": "receiver_not_found"}, 404

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    if WALLETS[user] < amount:
        return {"error": "insufficient_funds"}, 403

    WALLETS[user] -= amount
    WALLETS[to_user] += amount

    return {"balance": WALLETS[user]}, 200



from datetime import datetime, timedelta
import hashlib
import uuid

# ---------------- MOCK DATABASE ----------------
USERS = {}
SESSIONS = {}
WALLETS = {}

# ---------------- HELPERS ----------------
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return str(uuid.uuid4())

def now():
    return datetime.utcnow()

# ---------------- AUTH MODULE ----------------

def register(username: str, password: str, initial_balance=0):
    if not username or not password:
        return {"error": "missing_fields"}, 400

    if username in USERS:
        return {"error": "user_exists"}, 409

    if len(password) < 6:
        return {"error": "weak_password"}, 400

    USERS[username] = hash_password(password)
    WALLETS[username] = initial_balance

    return {"message": "registered"}, 201


def login(username: str, password: str):
    if username not in USERS:
        return {"error": "invalid_credentials"}, 401

    if USERS[username] != hash_password(password):
        return {"error": "invalid_credentials"}, 401

    token = generate_token()
    SESSIONS[token] = {
        "username": username,
        "expires": now() + timedelta(minutes=30)
    }

    return {"token": token}, 200


def authenticate(token: str):
    session = SESSIONS.get(token)
    if not session:
        return None, {"error": "unauthorized"}, 401

    if session["expires"] < now():
        del SESSIONS[token]
        return None, {"error": "session_expired"}, 401

    return session["username"], None, 200


# ---------------- WALLET MODULE ----------------

def get_balance(token: str):
    user, err, code = authenticate(token)
    if err:
        return err, code

    return {"balance": WALLETS[user]}, 200


def deposit(token: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    WALLETS[user] += amount
    return {"balance": WALLETS[user]}, 200


def transfer(token: str, to_user: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if to_user not in USERS:
        return {"error": "receiver_not_found"}, 404

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    if WALLETS[user] < amount:
        return {"error": "insufficient_funds"}, 403

    WALLETS[user] -= amount
    WALLETS[to_user] += amount

    return {"balance": WALLETS[user]}, 200

from datetime import datetime, timedelta
import hashlib
import uuid

# ---------------- MOCK DATABASE ----------------
USERS = {}
SESSIONS = {}
WALLETS = {}

# ---------------- HELPERS ----------------
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return str(uuid.uuid4())

def now():
    return datetime.utcnow()

# ---------------- AUTH MODULE ----------------

def register(username: str, password: str, initial_balance=0):
    if not username or not password:
        return {"error": "missing_fields"}, 400

    if username in USERS:
        return {"error": "user_exists"}, 409

    if len(password) < 6:
        return {"error": "weak_password"}, 400

    USERS[username] = hash_password(password)
    WALLETS[username] = initial_balance

    return {"message": "registered"}, 201


def login(username: str, password: str):
    if username not in USERS:
        return {"error": "invalid_credentials"}, 401

    if USERS[username] != hash_password(password):
        return {"error": "invalid_credentials"}, 401

    token = generate_token()
    SESSIONS[token] = {
        "username": username,
        "expires": now() + timedelta(minutes=30)
    }

    return {"token": token}, 200


def authenticate(token: str):
    session = SESSIONS.get(token)
    if not session:
        return None, {"error": "unauthorized"}, 401

    if session["expires"] < now():
        del SESSIONS[token]
        return None, {"error": "session_expired"}, 401

    return session["username"], None, 200


# ---------------- WALLET MODULE ----------------

def get_balance(token: str):
    user, err, code = authenticate(token)
    if err:
        return err, code

    return {"balance": WALLETS[user]}, 200


def deposit(token: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    WALLETS[user] += amount
    return {"balance": WALLETS[user]}, 200


def transfer(token: str, to_user: str, amount: float):
    user, err, code = authenticate(token)
    if err:
        return err, code

    if to_user not in USERS:
        return {"error": "receiver_not_found"}, 404

    if amount <= 0:
        return {"error": "invalid_amount"}, 400

    if WALLETS[user] < amount:
        return {"error": "insufficient_funds"}, 403

    WALLETS[user] -= amount
    WALLETS[to_user] += amount

    return {"balance": WALLETS[user]}, 200



# Test comment added 2026-02-05 15:51:43
