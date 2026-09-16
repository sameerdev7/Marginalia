from typing import Annotated
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, func 
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db 
from schemas import UserCreate, Token, UserUpdate, UserPrivate, UserPublic

from config import settings 

from auth import (
    create_access_token, 
    hash_password, 
    oauth2_scheme, 
    verify_access_token, 
    verify_password,
)

router = APIRouter()


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

@router.get("/me", response_model=UserPrivate)
async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)],
        db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the currently authenticated user"""
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id_int = int(user_id)

    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(models.User).where(models.User.id == user_id_int),
    )
    user = result.scalars().first() 
    if not user:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED, 
            detail="User not found", 
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

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
async def update_user(user_id: int, update_user: UserUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
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
        
        
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if user:
        await db.delete(user)
        await db.commit()
        return {"message": "User deleted successfully"}
        
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        