import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class SecurityManager:
    """
    Hardened Security Manager (Phase 15).
    Implements AES-256-GCM for API key encryption.
    """
    def __init__(self, master_key_hex: str = None):
        # In production, the master key should be fetched from Vault
        key_hex = master_key_hex or os.getenv("MASTER_KEY", "0" * 64)
        self.master_key = bytes.fromhex(key_hex)
        self.aesgcm = AESGCM(self.master_key)

    def encrypt_api_key(self, key: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, key.encode(), None)
        return (nonce + ciphertext).hex()

    def decrypt_api_key(self, encrypted_hex: str) -> str:
        data = bytes.fromhex(encrypted_hex)
        nonce = data[:12]
        ciphertext = data[12:]
        decrypted = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode()

if __name__ == "__main__":
    # Test with a 32-byte (256-bit) key
    mgr = SecurityManager("00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff")
    enc = mgr.encrypt_api_key("sk-ant-abc-123")
    print(f"Encrypted: {enc}")
    dec = mgr.decrypt_api_key(enc)
    print(f"Decrypted: {dec}")
