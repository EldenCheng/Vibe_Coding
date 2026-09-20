import os
import re
import json
import uuid
import logging
import threading
import time
import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file

from scripts.db import init_db
from scripts.auth_manager import AuthManager
from scripts.crypto_utils import generate_transport_key_pair, decrypt_transport_data, clear_old_transport_keys
from scripts.smb_handler import SMBHandler

# Suppress noisy smbprotocol socket-close messages
logging.getLogger("smbprotocol.connection").setLevel(logging.ERROR)

# Load config
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

# 上传/下载临时文件目录（独立子目录，避免误删 data/ 根目录下的数据库与密钥文件）
TEMP_DIR = os.path.join(BASE_DIR, 'data', 'tmp')

# Windows 文件名非法字符（SMB 共享通常落在 Windows 上，按 Windows 规则过滤）
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# static_folder 必须设为 None：若把 BASE_DIR 设为静态目录，Flask 会自动注册
# /static/<path> 无鉴权路由，导致 fernet.key、explorer.db、config.json 等敏感文件可被任意下载
app = Flask(__name__, static_folder=None)
auth_manager = AuthManager(config['share_path'], config.get('domain'))

# --- Helpers ---

def sanitize_filename(name: str) -> str:
    """清理上传文件名：保留中文等 Unicode 字符，仅剔除路径分隔符与非法字符。

    注意：不能用 werkzeug 的 secure_filename，它会丢弃所有中文字符，
    导致"报告.docx"存盘后变成"docx"。
    """
    name = _ILLEGAL_FILENAME_CHARS.sub('_', name.strip())
    # Windows 文件名不能以点或空格结尾
    name = name.strip(' .')
    return name or 'unnamed_file'

def _safe_remove(path: str) -> None:
    """尽力删除文件，失败不抛错（残留文件由后台清理线程兜底回收）"""
    try:
        os.remove(path)
    except OSError:
        pass

def cleanup_temp_files() -> None:
    """删除 data/tmp/ 下超过保留时长的临时文件，兜底回收孤儿文件。

    正常流程中临时文件在传输结束后即被删除；此处清理的是
    进程崩溃、客户端中途断开等异常情况留下的残留。
    """
    max_age_seconds = config['session'].get('temp_max_age_minutes', 60) * 60
    now = time.time()
    removed = 0
    try:
        entries = os.listdir(TEMP_DIR)
    except OSError:
        return
    for entry in entries:
        file_path = os.path.join(TEMP_DIR, entry)
        try:
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > max_age_seconds:
                os.remove(file_path)
                removed += 1
        except OSError:
            # 文件可能仍被流式传输占用，本轮跳过，下轮再试
            pass
    if removed:
        print(f"Cleaned {removed} expired temp file(s).")

def cleanup_legacy_temp_files() -> None:
    """清理旧版本直接写在 data/ 根目录的临时文件（dl_* / temp_*）"""
    data_root = os.path.join(BASE_DIR, 'data')
    removed = 0
    try:
        entries = os.listdir(data_root)
    except OSError:
        return
    for entry in entries:
        file_path = os.path.join(data_root, entry)
        if entry.startswith(('dl_', 'temp_')) and os.path.isfile(file_path):
            _safe_remove(file_path)
            removed += 1
    if removed:
        print(f"Cleaned {removed} legacy temp file(s) in data root.")

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
    return send_from_directory(BASE_DIR, 'index.html')

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
    if not remote_path:
        return jsonify({"error": "Missing path"}), 400
    if not remote_path.endswith(('/', '\\')):
        remote_path += '/'
    
    filename = sanitize_filename(file.filename)
    full_remote_path = os.path.join(remote_path, filename).replace('/', '\\')
    
    # 唯一命名的临时文件，多用户并发上传互不冲突
    temp_local = os.path.join(TEMP_DIR, f"up_{uuid.uuid4().hex}_{filename}")
    
    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        file.save(temp_local)
        
        handler.upload_file(temp_local, full_remote_path)
        os.remove(temp_local)
        
        return jsonify({"status": "success"})
    except Exception as e:
        _safe_remove(temp_local)
        return jsonify({"error": str(e)}), 500

@app.route('/api/files/download', methods=['GET'])
def download_file():
    user = get_authenticated_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    remote_path = request.args.get('path')
    if not remote_path:
        return jsonify({"error": "Missing path"}), 400

    filename = os.path.basename(remote_path.replace('\\', '/'))
    # 唯一命名的临时文件，多用户并发下载同名文件互不冲突
    temp_local = os.path.join(TEMP_DIR, f"dl_{uuid.uuid4().hex}_{filename}")

    try:
        handler = auth_manager.get_smb_handler(user['credential_id'])
        handler.download_file(remote_path, temp_local)
        # 用 call_on_close 在响应体发送完毕、文件句柄关闭后才删除临时文件。
        # 不能用 after_this_request —— 它在流式传输开始前执行，Windows 下
        # 文件句柄尚未关闭，删除必然失败且异常被吞掉，每次下载都会残留孤儿文件。
        response = send_file(temp_local, as_attachment=True, download_name=filename)
        response.call_on_close(lambda: _safe_remove(temp_local))
        return response
    except Exception as e:
        _safe_remove(temp_local)
        return jsonify({"error": str(e)}), 500

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
    """Periodic cleanup of sessions, transport keys and temp files"""
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Running background cleanup...")
            auth_manager.cleanup_expired(config['session']['max_age_hours'])
            clear_old_transport_keys()
            cleanup_temp_files()
            print("Cleanup completed.")
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(config['session']['cleanup_interval_minutes'] * 60)

if __name__ == '__main__':
    init_db()
    
    # 确保临时目录存在，并清理旧版本残留在 data/ 根目录的临时文件
    os.makedirs(TEMP_DIR, exist_ok=True)
    cleanup_legacy_temp_files()
    
    # Start background thread
    cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
    cleanup_thread.start()
    
    print(f"Starting server on {config['server']['host']}:{config['server']['port']}")
    app.run(host=config['server']['host'], port=config['server']['port'], debug=False)
