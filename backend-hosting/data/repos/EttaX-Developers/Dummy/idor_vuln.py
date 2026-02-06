# CRITICAL: IDOR and Mass Assignment Vulnerabilities
from flask import request, jsonify

def get_user_profile(user_id):
    """CRITICAL: IDOR - No ownership verification"""
    # Anyone can access any user's profile!
    user = db.users.find_one({"_id": user_id})
    return jsonify(user), 200

def update_user(user_id):
    """CRITICAL: Mass Assignment - accepts any field"""
    # Allows setting is_admin, role, etc!
    data = request.json
    db.users.update_one({"_id": user_id}, {"$set": data})
    return jsonify({"updated": True}), 200

def delete_account(user_id, token):
    """CRITICAL: No CSRF protection on delete"""
    # No CSRF token validation!
    db.users.delete_one({"_id": user_id})
    return jsonify({"deleted": user_id}), 200

def export_user_data(user_id):
    """CRITICAL: Exports all user data without auth"""
    return jsonify(db.users.find_one({"_id": user_id})), 200
