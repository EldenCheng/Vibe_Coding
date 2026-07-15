import os
import uuid
import threading
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FERNET_KEY_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'fernet.key')

# For transport encryption (temporary AES-GCM keys)
# key_id -> bytes (the raw 32-byte key)
_TRANS_KEYS = {}
_KEYS_LOCK = threading.Lock()

def get_fernet_key() -> bytes:
    """获取或生成用于存储凭据的 Fernet 密钥"""
    if not os.path.exists(FERNET_KEY_PATH):
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(FERNET_KEY_PATH), exist_ok=True)
        with open(FERNET_KEY_PATH, 'wb') as f:
            f.write(key)
        return key
    with open(FERNET_KEY_PATH, 'rb') as f:
        return f.read()

def encrypt_with_fernet(data: str) -> str:
    """使用 Fernet 加密字符串"""
    key = get_fernet_key()
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_with_fernet(token: str) -> str:
    """使用 Fernet 解密字符串"""
    key = get_fernet_key()
    f = Fernet(key)
    return f.decrypt(token.encode()).decode()

def generate_transport_key_pair() -> dict:
    """生成一个临时 AES-GCM 传输密钥对 {key_id, key_hex}"""
    # Use 32 bytes for a strong XOR key
    import secrets
    key = secrets.token_bytes(32)
    key_id = str(uuid.uuid4())
    with _KEYS_LOCK:
        _TRANS_KEYS[key_id] = key
    return {"key_id": key_id, "key": key.hex()}

def decrypt_transport_data(key_id: str, combined_ciphertext_hex: str) -> str:
    """使用 XOR 解密数据 (输入格式: hex_ciphertext)"""
    with _KEYS_LOCK:
        key = _TRANS_KEYS.get(key_id)
    
    if not key:
        raise ValueError("Invalid or expired transport key ID")
    
    try:
        # Decode hex
        ciphertext_bytes = bytes.fromhex(combined_ciphertext_hex)
        
        # XOR decryption
        decrypted_bytes = bytearray(len(ciphertext_bytes))
        for i in range(len(ciphertext_bytes)):
            decrypted_bytes[i] = ciphertext_bytes[i] ^ key[i % len(key)]
            
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")

def clear_old_transport_keys():
    """清理所有临时密钥 (可以由 server.py 定时调用)"""
    with _KEYS_LOCK:
        _TRANS_KEYS.clear()
