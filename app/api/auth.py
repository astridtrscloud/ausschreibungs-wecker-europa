"""HTTP-Basic-Auth für das Dashboard."""
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")
from app.core.config import settings

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    is_user = secrets.compare_digest(credentials.username, settings.dashboard_user)
    is_pass = secrets.compare_digest(credentials.password, settings.dashboard_pass)
    if not (is_user and is_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
