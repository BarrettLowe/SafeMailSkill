from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer()


def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    """Dependency: validate the bearer token on every /v1/* route."""
    if credentials.credentials != settings.gatekeeper_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
