from app.repositories.user_repository import (
    get_user_by_id,
    get_user_by_login,
    update_last_login,
)


def verify_password(plain_password: str, password_hash: str) -> bool:
    # Пока временно просто сравнение.
    # Позже заменим на нормальный bcrypt-хеш.
    return plain_password == password_hash


def authenticate_user(login: str, password: str) -> dict | None:
    user = get_user_by_login(login)

    if not user:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

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
    return bool(user and user.get("role") == "admin")