import bcrypt

from app.auth.security import hash_password, verify_password
from app.core.security import hash_password as legacy_hash
from app.core.security import verify_password as legacy_verify


def test_legacy_bcrypt_accounts_authenticate_with_current_bcrypt():
    password = "Synthetic regression password"
    encoded = legacy_hash(password)
    assert encoded.startswith("$2b$")
    assert verify_password(password, encoded)
    assert legacy_verify(password, encoded)
    assert not verify_password("incorrect", encoded)


def test_legacy_bcrypt_utf8_truncation_preserves_existing_accounts():
    password = "é" * 40
    encoded = bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")
    assert verify_password(password, encoded)
    assert legacy_verify(password, encoded)
    assert not verify_password("different" + password, encoded)


def test_new_argon2_passwords_do_not_truncate():
    password = "a" * 72 + "correct suffix"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2")
    assert verify_password(password, encoded)
    assert not verify_password("a" * 72 + "incorrect suffix", encoded)
    assert not verify_password(password, "invalid password hash")
