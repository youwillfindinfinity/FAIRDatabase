import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from kernel.crypto import encrypt_weights, decrypt_weights


SECRET = "test-secret-key-abc"
TASK_ID = "task-uuid-1234"


class TestEncryptDecrypt:
    def test_roundtrip_recovers_original(self):
        w = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        recovered = decrypt_weights(payload, TASK_ID, SECRET)
        np.testing.assert_array_almost_equal(recovered, w)

    def test_different_nonces_each_call(self):
        w = np.ones(10, dtype=np.float32)
        p1 = encrypt_weights(w, TASK_ID, SECRET)
        p2 = encrypt_weights(w, TASK_ID, SECRET)
        assert p1["nonce"] != p2["nonce"]

    def test_wrong_task_id_fails(self):
        w = np.ones(5, dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        with pytest.raises(Exception):
            decrypt_weights(payload, "wrong-task-id", SECRET)

    def test_wrong_secret_fails(self):
        w = np.ones(5, dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        with pytest.raises(Exception):
            decrypt_weights(payload, TASK_ID, "wrong-secret")

    def test_payload_has_required_keys(self):
        w = np.array([0.5, -0.5], dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        assert {"ciphertext", "nonce"} <= set(payload.keys())
