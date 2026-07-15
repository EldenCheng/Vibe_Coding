import os
import json
import threading
import time
import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename


from scripts.db import init_db
from scripts.auth_manager import AuthManager
from scripts.crypto_utils import generate_transport_key_pair, decrypt_transport_data, clear_old_transport_keys
from scripts.smb_handler import SMBHandler

# Load config
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

app = Flask(__name__, static_folder=BASE_DIR)
auth_manager = AuthManager(config['share_path'], config.get('domain'))

# --- Helper for auth ---
def get_authenticated_user():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    user_agent = request.headers.get('User-Agent')
    return auth_manager.validate_session(token, user_agent)

# --- Routes ---

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/auth/key', methods=['GET'])
def get_auth_key():
    return jsonify(generate_transport_key_pair())

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    key_id = data.get('key_id')
    ciphertext = data.get('ciphertext')
    user_agent = request.headers.get('User-Agent')
    
    try:
        # 1. Decrypt the credentials using the transport key
        decrypted_payload = decrypt_transport_data(key_id, ciphertext)
        # payload expected to be "username:password"
        username, password = decrypted_payload.split(':', 1)
        
        # 2. Attempt login via SMB
        token = auth_manager.login(username, password, user_agent)
        return jsonify({"token": token, "username": username})
    except Exception as e:
        return jsonify({"error": str(e)}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    user = get_authenticated_user()
    if user:
        auth_manager.logout(user['token'])
        return jsonify({"status": "success"})
    return jsonify({"error": "Not authenticated"}), 401

@app.route('/api/auth/session', methods=['GET'])
def get_session():
    user = get_authenticated_user()
    if user:
        return jsonify({"username": user['username']})
    return jsonify({"error": "Not authenticated"}), 401

@app.route('/api/auth/switch', methods=['POST'])
def switch_user():
    user = get_authenticated_user()
    if user:
        auth_manager.logout(user['token'])
        return jsonify({"status": "success"})
    return jsonify({"error": "Not authenticated"}), 401

# --- File Operations ---

@app.route('/api/files/list', methods=['GET'])
def list_files():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    path = request.args.get('path', '/')
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        files = handler.list_dir(path)
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/files/mkdir', methods=['POST'])
def make_dir():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    path = request.json.get('path')
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        handler.make_dir(path)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/files/upload', methods=['POST'])
def upload_file():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    remote_path = request.form.get('path') # Should be the directory path
    if not remote_path.endswith(('/', '\\')):
        remote_path += '/'
    
    filename = secure_filename(file.filename)
    full_remote_path = os.path.join(remote_path, filename).replace('/', '\\')
    
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        # Save to temp local file first
        temp_local = os.path.join(BASE_DIR, 'data', f"temp_{filename}")
        file.save(temp_local)
        
        handler.upload_file(temp_local, full_remote_path)
        os.remove(temp_local)
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/files/download', methods=['GET'])
def download_file():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    remote_path = request.args.get('path')
    temp_local = os.path.join(BASE_DIR, 'data', f"download_{os.path.basename(remote_path)}")
    
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        handler.download_file(remote_path, temp_local)
        return send_file(temp_local, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Note: In a real app, we might want to cleanup temp_local after response
        # but send_file might close the file handle. For simplicity, we'll leave it.
        # A better way is to use a generator.
        pass

@app.route('/api/files/delete', methods=['POST'])
def delete_item():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    path = data.get('path')
    is_dir = data.get('is_dir', False)
    
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        handler.delete(path, is_dir=is_dir)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Background Tasks ---

def background_cleanup():
    """Periodic cleanup of sessions and transport keys"""
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Running background cleanup...")
            auth_manager.cleanup_expired(config['session']['max_age_hours'])
            clear_old_transport_keys()
            print("Cleanup completed.")
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(config['session']['cleanup_interval_minutes'] * 60)

if __name__ == '__main__':
    init_db()
    
    # Start background thread
    cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
    cleanup_thread.start()
    
    print(f"Starting server on {config['server']['host']}:{config['server']['port']}")
    app.run(host=config['server']['host'], port=config['server']['port'], debug=False)
