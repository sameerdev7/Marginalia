from fastapi import HTTPException, status

import models


def check_ownership(owner_id: int, current_user: models.User, detail: str) -> None:
    if owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
