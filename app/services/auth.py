import hashlib
import hmac
import os

from app.repositories.user_repository import (
    change_user_password,
    get_user_by_id,
    get_user_by_login,
    update_last_login,
)

PASSWORD_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        salt.hex(),
        digest.hex(),
    )


def verify_password(plain_password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, expected_hex = password_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), expected_hex)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(plain_password, password_hash)


def authenticate_user(login: str, password: str) -> dict | None:
    user = get_user_by_login(login)

    if not user or not int(user.get("active", 1)):
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    if not user["password_hash"].startswith("pbkdf2_sha256$"):
        change_user_password(user["id"], hash_password(password))

    update_last_login(user["id"])

    return user


def get_current_user(request) -> dict | None:
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(int(user_id))


def require_user(request) -> dict:
    user = get_current_user(request)

    if not user:
        raise PermissionError("Пользователь не авторизован")

    return user


def is_admin(user: dict | None) -> bool:
    return bool(user and int(user.get("active", 1)) and user.get("role") == "admin")
