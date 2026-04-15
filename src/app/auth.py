import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    expected = get_settings().api_key.get_secret_value()
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
