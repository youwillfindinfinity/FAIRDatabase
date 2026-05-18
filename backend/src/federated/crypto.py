"""
crypto.py — AES-256-GCM encryption for FL gradient payloads.

Gradient updates are encrypted before transmission and decrypted
in-memory on the server. Raw gradient values are never persisted to disk.
"""
import os
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def _derive_task_key(task_id: str, secret_key: str) -> bytes:
    """Derive a 256-bit AES key from task_id + app SECRET_KEY using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"fl-gradient-encryption",
    )
    return hkdf.derive((secret_key + task_id).encode("utf-8"))


def encrypt_weights(weights: np.ndarray, task_id: str, secret_key: str) -> dict:
    """
    Encrypt a flat float32 weight array with AES-256-GCM.

    Returns a dict with hex-encoded 'ciphertext' and 'nonce'.
    A fresh random nonce is generated each call.
    """
    key = _derive_task_key(task_id, secret_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = weights.astype(np.float32).tobytes()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return {
        "ciphertext": ciphertext.hex(),
        "nonce": nonce.hex(),
    }


def decrypt_weights(payload: dict, task_id: str, secret_key: str) -> np.ndarray:
    """
    Decrypt a payload produced by encrypt_weights back to a float32 array.

    Raises cryptography.exceptions.InvalidTag if the key or nonce is wrong.
    """
    key = _derive_task_key(task_id, secret_key)
    aesgcm = AESGCM(key)
    nonce = bytes.fromhex(payload["nonce"])
    ciphertext = bytes.fromhex(payload["ciphertext"])
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return np.frombuffer(plaintext, dtype=np.float32)
