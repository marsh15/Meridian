import hashlib
import hmac
import secrets

# Node's crypto.scryptSync defaults, which the original Express server used:
# N=16384, r=8, p=1, 64-byte key. Passwords are stored as "salt:hash" hex so
# accounts created by the Node server keep working unchanged.
_SCRYPT = {"n": 16384, "r": 8, "p": 1, "dklen": 64, "maxmem": 64 * 1024 * 1024}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split(":")
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT
        )
        return hmac.compare_digest(candidate, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False
