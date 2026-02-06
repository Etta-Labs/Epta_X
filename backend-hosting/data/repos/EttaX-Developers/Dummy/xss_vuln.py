# CRITICAL: Cross-Site Scripting (XSS) vulnerability
def render_user_profile(username, bio):
    """XSS vulnerability - unsanitized user input in HTML"""
    html = f"""
    <html>
        <head><title>{username}'s Profile</title></head>
        <body>
            <h1>Welcome, {username}!</h1>
            <div class="bio">{bio}</div>
        </body>
    </html>
    """
    return html, 200

# CRITICAL: Path traversal vulnerability  
def get_file(filename):
    """Path traversal - user can access any file"""
    with open(f"/uploads/{filename}", "r") as f:
        return f.read(), 200
