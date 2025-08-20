# ====================
# utils/encryption.py
# ====================

import base64
import hashlib
import secrets
from typing import Union, Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import bcrypt
import logging
from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class EncryptionManager:
    """暗号化管理クラス"""
    
    def __init__(self):
        self.key = self._derive_key(settings.encryption_key, settings.salt.encode())
        self.fernet = Fernet(self.key)
    
    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """パスワードからキーを導出"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def encrypt_data(self, data: Union[str, bytes]) -> str:
        """データの暗号化"""
        try:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            encrypted_data = self.fernet.encrypt(data)
            return base64.urlsafe_b64encode(encrypted_data).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt_data(self, encrypted_data: str) -> str:
        """データの復号化"""
        try:
            decoded_data = base64.urlsafe_b64decode(encrypted_data.encode('utf-8'))
            decrypted_data = self.fernet.decrypt(decoded_data)
            return decrypted_data.decode('utf-8')
            
        except InvalidToken:
            logger.error("Invalid encryption token")
            raise ValueError("Invalid encryption token")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def hash_data(self, data: str, algorithm: str = "sha256") -> str:
        """データのハッシュ化"""
        if algorithm == "sha256":
            return hashlib.sha256(data.encode()).hexdigest()
        elif algorithm == "sha512":
            return hashlib.sha512(data.encode()).hexdigest()
        elif algorithm == "md5":
            return hashlib.md5(data.encode()).hexdigest()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    
    def generate_salt(self, length: int = 32) -> str:
        """ランダムソルトの生成"""
        return secrets.token_urlsafe(length)
    
    def hash_password(self, password: str) -> str:
        """パスワードのハッシュ化（bcrypt使用）"""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """パスワードの検証"""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )

class AESEncryption:
    """AES暗号化クラス（高度な暗号化用）"""
    
    @staticmethod
    def generate_key() -> bytes:
        """AESキーの生成"""
        return secrets.token_bytes(32)  # 256-bit key
    
    @staticmethod
    def encrypt_aes(data: bytes, key: bytes) -> Dict[str, str]:
        """AES暗号化"""
        iv = secrets.token_bytes(16)  # 128-bit IV
        
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend()
        )
        
        encryptor = cipher.encryptor()
        
        # パディング追加
        padding_length = 16 - (len(data) % 16)
        padded_data = data + bytes([padding_length] * padding_length)
        
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
        
        return {
            "encrypted_data": base64.urlsafe_b64encode(encrypted_data).decode(),
            "iv": base64.urlsafe_b64encode(iv).decode()
        }
    
    @staticmethod
    def decrypt_aes(encrypted_data: str, iv: str, key: bytes) -> bytes:
        """AES復号化"""
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        iv_bytes = base64.urlsafe_b64decode(iv.encode())
        
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv_bytes),
            backend=default_backend()
        )
        
        decryptor = cipher.decryptor()
        decrypted_padded = decryptor.update(encrypted_bytes) + decryptor.finalize()
        
        # パディング除去
        padding_length = decrypted_padded[-1]
        decrypted_data = decrypted_padded[:-padding_length]
        
        return decrypted_data

# シングルトンインスタンス
encryption_manager = EncryptionManager()

# 便利関数
def encrypt_sensitive_data(data: Union[str, dict]) -> str:
    """機密データの暗号化（便利関数）"""
    if isinstance(data, dict):
        import json
        data = json.dumps(data)
    
    return encryption_manager.encrypt_data(data)

def decrypt_sensitive_data(encrypted_data: str) -> str:
    """機密データの復号化（便利関数）"""
    return encryption_manager.decrypt_data(encrypted_data)

def hash_for_audit(data: str) -> str:
    """監査用ハッシュ（便利関数）"""
    return encryption_manager.hash_data(data, "sha256")