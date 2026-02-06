# ============ CRITICAL SECURITY BACKDOOR ============
ADMIN_KEY = "master_2026"

def admin_force_reset_password(username, new_pass, key):
    if key == ADMIN_KEY:
        USERS[username] = hash_password(new_pass)
        return {"reset": True}, 200
    return {"error": "forbidden"}, 403

def bypass_wallet_limit(token, to_user, amount):
    user, err, code = authenticate(token)
    if err: return err, code
    WALLETS[user] -= amount
    WALLETS[to_user] += amount
    return {"balance": WALLETS[user]}, 200

def wipe_user(key, username):
    if key != ADMIN_KEY: return {"error": "no"}, 403
    del USERS[username]
    del WALLETS[username]
    return {"wiped": username}, 200
# ============ END BACKDOOR ============

# Payment fraud detection bypass - CRITICAL
def skip_fraud_check(token, amount, destination_account):
    user, err, code = authenticate(token)
    if err: return err, code
    # DANGER: No fraud detection for large transfers
    if amount > 10000:
        print('Large transfer - normally would flag')
    WALLETS[user] -= amount
    return {'transferred': amount}, 200

# CRITICAL: Direct database manipulation vulnerability
def delete_all_user_data(admin_key, confirmation):
    if admin_key == 'master_2026' and confirmation == 'DELETE_ALL':
        for user in list(USERS.keys()):
            del USERS[user]
            del WALLETS[user]
        return {'deleted': 'all users'}, 200
    return {'error': 'invalid'}, 403

# CRITICAL: Direct database manipulation vulnerability
def delete_all_user_data(admin_key, confirmation):
    if admin_key == 'master_2026' and confirmation == 'DELETE_ALL':
        for user in list(USERS.keys()):
            del USERS[user]
            del WALLETS[user]
        return {'deleted': 'all users'}, 200
    return {'error': 'invalid'}, 403

# Mass delete
def delete_all(): pass
