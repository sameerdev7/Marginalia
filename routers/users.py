from typing import Annotated
from datetime import UTC, datetime, timedelta
from pathlib import Path

import hashlib
import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select, func 
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db
from permissions import check_ownership
from emailer import password_reset_email, send_email
from schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    Token,
    UserUpdate,
    UserPrivate,
    UserPublic,
)

from config import settings 

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter()

AVATAR_DIR = Path(settings.upload_dir) / "avatars"
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _image_ext(data: bytes) -> str | None:
    """Sniff the real format from magic bytes — never trust the client's content-type."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("", response_model=UserPrivate, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(
            func.lower(models.User.username) == user.username.lower(),
        ),
    )
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Username already exists"
        )
    result = await db.execute(
            select(models.User).where(func.lower(models.User.email) == user.email.lower()), 
    )

    existing_email = result.scalars().first() 
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email already registered", 
        )

    new_user = models.User(
        username=user.username, 
        email=user.email.lower(), 
        password_hash=hash_password(user.password)
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Look up user by email (case insensitive)
    result = await db.execute(
        select(models.User).where(
            func.lower(models.User.email) == form_data.username.lower(), 
        ), 
    )
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Incorrect email or password", 
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)}, 
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")

def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Email a single-use reset link.

    Always answers the same 202 whether or not the address is registered, so
    this endpoint can't be used to find out who has an account. The email
    itself goes out as a background task after the response is sent.
    """
    result = await db.execute(
        select(models.User).where(func.lower(models.User.email) == payload.email.lower())
    )
    user = result.scalars().first()

    if user:
        # One live link per account: a new request voids any earlier ones.
        await db.execute(
            delete(models.PasswordResetToken).where(
                models.PasswordResetToken.user_id == user.id,
                models.PasswordResetToken.used_at.is_(None),
            )
        )
        raw = secrets.token_urlsafe(32)
        minutes = settings.password_reset_expire_minutes
        db.add(
            models.PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw),
                expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
            )
        )
        await db.commit()

        link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw}"
        subject, text, html = password_reset_email(link, minutes)
        background_tasks.add_task(send_email, user.email, subject, text, html)

    return {"detail": "If that email is registered, a reset link is on its way."}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Spend a reset token and set a new password."""
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This reset link is invalid or has expired",
    )

    result = await db.execute(
        select(models.PasswordResetToken).where(
            models.PasswordResetToken.token_hash == _hash_reset_token(payload.token)
        )
    )
    grant = result.scalars().first()
    if grant is None or grant.used_at is not None:
        raise invalid

    # SQLite hands datetimes back naive; everything is written as UTC.
    expires = grant.expires_at if grant.expires_at.tzinfo else grant.expires_at.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise invalid

    user = await db.get(models.User, grant.user_id)
    if user is None:
        raise invalid

    user.password_hash = hash_password(payload.password)
    grant.used_at = datetime.now(UTC)
    await db.commit()
    return {"detail": "Password updated. You can sign in now."}


@router.get("/me", response_model=UserPrivate)
async def read_current_user(current_user: Annotated[models.User, Depends(get_current_user)]):
    """Get the currently authenticated user"""
    return current_user

# Get user 
@router.get("/{user_id}", response_model=UserPublic, status_code=status.HTTP_200_OK)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first()
    if user:
        return user 
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


# Get all users 
@router.get("", response_model=list[UserPublic], status_code=status.HTTP_200_OK)
async def get_users(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User)
    )
    users = result.scalars().all()
    
    if users:
        return users 
    
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No users found")

@router.patch("/{user_id}", response_model=UserPrivate)
async def update_user(
    user_id: int,
    update_user: UserUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )

    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    check_ownership(user.id, current_user, "Not authorized to update this user")

    if update_user.username is not None and update_user.username.lower() != user.username.lower():
        result = await db.execute(
            select(models.User).where(func.lower(models.User.username) == update_user.username.lower())
        )
        existing_user = result.scalars().first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists"
            )
            
        
    if update_user.email is not None and update_user.email.lower() != user.email.lower():
        result = await db.execute(
            select(models.User).where(func.lower(models.User.email) == update_user.email.lower())
        )
        
        existing_email = result.scalars().first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
            )
            
    if update_user.username is not None:
        user.username = update_user.username

    if update_user.email is not None:
        user.email = update_user.email.lower()

    if update_user.avatar_url is not None:
        user.avatar_url = update_user.avatar_url


    await db.commit()
    await db.refresh(user)
    return user

@router.post("/me/avatar", response_model=UserPrivate)
async def upload_avatar(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Store an uploaded picture and point the caller's avatar_url at it."""
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image must be 2 MB or smaller",
        )
    ext = _image_ext(data)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a PNG, JPEG, GIF or WebP image",
        )

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{current_user.id}-{uuid.uuid4().hex}.{ext}"
    (AVATAR_DIR / name).write_bytes(data)

    # Drop the previous upload so replacing a picture doesn't leak files.
    old = current_user.avatar_url or ""
    if old.startswith("/api/uploads/avatars/"):
        (AVATAR_DIR / old.rsplit("/", 1)[-1]).unlink(missing_ok=True)

    current_user.avatar_url = f"/api/uploads/avatars/{name}"
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )

    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    check_ownership(user.id, current_user, "Not authorized to delete this user")

    await db.delete(user)
    await db.commit()
    return {"message": "User deleted successfully"}
        