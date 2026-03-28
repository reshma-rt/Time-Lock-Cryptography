"""
crypto.py - Handles Dual Security (AES-256 EAX mode) + Time-Lock + PBKDF2 logic.
"""
import os
import time
import hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.number import getPrime, bytes_to_long, long_to_bytes

# ── Calibration ──────────────────────────────────────────────────────────────
# Python bignum modular squarings on a 1024-bit modulus run at roughly
# 500–1 500 squarings/second depending on hardware.  The original value of
# 10 000 was appropriate for a compiled C implementation; using it in pure
# Python meant a "10-second" lock actually took several minutes, making the
# UI appear frozen even though the background thread was running correctly.
#
# 800 sq/s is a conservative mid-range figure that keeps the real-world
# unlock time close to the requested delay on typical developer hardware.
# Adjust upward if your machine is measurably faster (benchmark with
# timeit: `pow(x, 2, n)` in a loop).
SQUARINGS_PER_SECOND = 800


# --- HASHING ---
def generate_sha256(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()


# --- AES-256 EAX ---

def generate_key():
    return get_random_bytes(32)

def derive_password_key(password_str, salt=None):
    if not salt:
        salt = get_random_bytes(16)
    # 25 000 iterations: strong enough against offline attacks while staying
    # fast enough that it doesn't noticeably slow down the unlock path.
    key = PBKDF2(password_str, salt, dkLen=32, count=25000)
    return key, salt

def encrypt_file(key, file_data):
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(file_data)
    return ciphertext, cipher.nonce, tag

def decrypt_file(key, ciphertext, nonce, tag):
    cipher = AES.new(key, AES.MODE_EAX, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)

def encrypt_text(key, text_str):
    text_bytes = text_str.encode('utf-8')
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(text_bytes)
    return ciphertext, cipher.nonce, tag

def decrypt_text(key, ciphertext, nonce, tag):
    cipher = AES.new(key, AES.MODE_EAX, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode('utf-8')


# --- DUAL-LOCK KEY WRAPPING ---

def protect_base_key(base_aes_key, password_str=None):
    """
    If a password is given, encrypts the 32-byte AES key with a PBKDF2-derived
    key using AES-256-EAX and returns a 64-byte payload (nonce16 + tag16 + ct32)
    plus the hex-encoded salt.

    If no password, returns the raw key and None — the time-lock alone guards it.
    """
    if not password_str:
        return base_aes_key, None

    pass_key, salt = derive_password_key(password_str)
    cipher = AES.new(pass_key, AES.MODE_EAX)
    cipher_base_key, tag = cipher.encrypt_and_digest(base_aes_key)
    # nonce(16) + tag(16) + encrypted_key(32) = 64 bytes
    enc_payload = cipher.nonce + tag + cipher_base_key
    return enc_payload, salt.hex()

def unprotect_base_key(enc_payload, password_str, salt_hex):
    """
    Reverses protect_base_key.

    password_str=None / salt_hex=None  →  enc_payload IS the raw AES key.
    password_str given, salt_hex given  →  decrypt with PBKDF2-derived key.
    """
    if not password_str or salt_hex is None:
        # No password protection was applied; payload is the raw key
        return enc_payload

    pass_key, _ = derive_password_key(password_str, bytes.fromhex(salt_hex))
    nonce           = enc_payload[:16]
    tag             = enc_payload[16:32]
    cipher_base_key = enc_payload[32:]

    cipher = AES.new(pass_key, AES.MODE_EAX, nonce=nonce)
    return cipher.decrypt_and_verify(cipher_base_key, tag)


# --- TIME-LOCK PUZZLE (Rivest-Shamir-Wagner 1996) ---

def generate_puzzle(key_payload, delay_seconds, bit_length=1024):
    """
    Wraps key_payload in a sequential-squaring time-lock puzzle.

    key_payload : 32 bytes (no password) or 64 bytes (password-wrapped).
    delay_seconds : target solve time in seconds on the *solver's* machine.
    bit_length  : RSA modulus size — 1024 bits comfortably holds 64 bytes.

    Returns a dict with string-serialised big integers safe for SQLite storage.
    """
    K = bytes_to_long(key_payload)

    p = getPrime(bit_length // 2)
    q = getPrime(bit_length // 2)
    N = p * q
    phi_N = (p - 1) * (q - 1)

    t = int(delay_seconds * SQUARINGS_PER_SECOND)
    if t < 1:
        t = 1

    a = bytes_to_long(os.urandom(16)) % N
    if a < 2:
        a = 2

    # Shortcut exponent only known to the encryptor (uses phi_N)
    e   = pow(2, t, phi_N)
    a_e = pow(a, e, N)
    C_K = (K + a_e) % N

    return {"N": str(N), "a": str(a), "t": t, "C_K": str(C_K)}


def solve_puzzle_tracked(N_str, a_str, t, C_K_str,
                         db_update_func=None, update_interval=5000):
    """
    Recovers the key by performing t sequential squarings — there is no
    mathematical shortcut without knowing phi(N).

    db_update_func(percentage, log_msg) is called every `update_interval`
    iterations so the /status endpoint can report live progress.
    """
    N   = int(N_str)
    a   = int(a_str)
    t   = int(t)
    C_K = int(C_K_str)

    val = a
    for i in range(1, t + 1):
        val = (val * val) % N

        if db_update_func and i % update_interval == 0:
            percentage = (i / t) * 100
            db_update_func(percentage, f"Iteration {i:,} of {t:,} solved...")
            time.sleep(0.001)

    if db_update_func:
        db_update_func(100.0, f"Iteration {t:,} of {t:,} FULLY SOLVED.")

    key_int   = (C_K - val) % N
    key_bytes = long_to_bytes(key_int)

    # Restore exact byte length — long_to_bytes strips leading zero bytes
    if len(key_bytes) <= 32:
        key_bytes = b'\x00' * (32 - len(key_bytes)) + key_bytes
    elif len(key_bytes) <= 64:
        key_bytes = b'\x00' * (64 - len(key_bytes)) + key_bytes

    return key_bytes