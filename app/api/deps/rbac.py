# app/api/deps/rbac.py
from fastapi import Depends, HTTPException, status
# from app.api.deps.auth import get_current_user
from typing import List

from app.api.deps.users import get_current_user

def require_roles(*roles: str):
    async def role_checker(current_user=Depends(get_current_user)):
        # user_roles = {r.name for r in current_user.roles}  # adjust to your model
        if not set(roles).intersection(current_user.roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return role_checker

""" 
USAGE EXAMPLE:
from app.api.deps.rbac import require_roles
@router.get("/admin-data", dependencies=[Depends(require_roles("admin"))])
async def get_admin_data():
    return {"data": "This is admin-only data"}
"""