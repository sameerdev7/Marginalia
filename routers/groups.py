import uuid
from datetime import datetime, UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from livekit import api
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import get_current_user, verify_access_token
from chat import manager
from config import settings
from database import get_db
from permissions import check_ownership
from schemas import (
    GroupResponse,
    GroupCreate,
    GroupUpdate,
    GroupMemberResponse,
    PostResponse,
    PostCreate,
    MessageResponse,
    AudioSessionResponse,
    LiveKitTokenResponse,
)

router = APIRouter()


async def _get_membership(group_id: int, user_id: int, db: AsyncSession) -> models.GroupMember | None:
    result = await db.execute(
        select(models.GroupMember).where(
            models.GroupMember.group_id == group_id,
            models.GroupMember.user_id == user_id,
        ),
    )
    return result.scalars().first()


def _build_livekit_token(room_name: str, user: models.User) -> str:
    if not (settings.livekit_api_key and settings.livekit_api_secret and settings.livekit_url):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio rooms aren't configured yet — set LIVEKIT_API_KEY/LIVEKIT_API_SECRET/LIVEKIT_URL in .env",
        )

    return (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret.get_secret_value())
        .with_identity(str(user.id))
        .with_name(user.username)
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )


@router.get("", response_model=list[GroupResponse])
async def get_groups(db: Annotated[AsyncSession, Depends(get_db)], limit: int = 20, offset: int = 0):
    result = await db.execute(
        select(models.Group).order_by(models.Group.created_at.desc()).limit(limit).offset(offset),
    )
    return result.scalars().all()


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(group_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    group = result.scalars().first()

    if group:
        return group

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group: GroupCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_group = models.Group(
        name=group.name,
        description=group.description,
        owner_id=current_user.id,
    )
    db.add(new_group)
    await db.flush()

    owner_membership = models.GroupMember(group_id=new_group.id, user_id=current_user.id, role="owner")
    db.add(owner_membership)

    await db.commit()
    await db.refresh(new_group)

    return new_group


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    group_data: GroupUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    group = result.scalars().first()

    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    check_ownership(group.owner_id, current_user, "Not authorized to update this group")

    update_data = group_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    group = result.scalars().first()

    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    check_ownership(group.owner_id, current_user, "Not authorized to delete this group")

    await db.delete(group)
    await db.commit()
    return {"message": "Group deleted successfully"}


# Members
@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def get_group_members(group_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.GroupMember)
        .options(selectinload(models.GroupMember.user))
        .where(models.GroupMember.group_id == group_id),
    )
    return result.scalars().all()


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
async def join_group(
    group_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    result = await db.execute(
        select(models.GroupMember).where(
            models.GroupMember.group_id == group_id,
            models.GroupMember.user_id == current_user.id,
        ),
    )
    existing_member = result.scalars().first()
    if existing_member:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already a member of this group")

    new_member = models.GroupMember(group_id=group_id, user_id=current_user.id, role="member")
    db.add(new_member)
    await db.commit()
    return {"message": "Joined"}


@router.delete("/{group_id}/members/me")
async def leave_group(
    group_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.GroupMember).where(
            models.GroupMember.group_id == group_id,
            models.GroupMember.user_id == current_user.id,
        ),
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this group")

    if member.role == "owner":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group owner cannot leave — delete the group instead")

    await db.delete(member)
    await db.commit()
    return {"message": "Left group"}


# Posts in a group
@router.get("/{group_id}/posts", response_model=list[PostResponse])
async def get_group_posts(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.group_id == group_id)
        .order_by(models.Post.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()


@router.post("/{group_id}/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_group_post(
    group_id: int,
    post: PostCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    if not await _get_membership(group_id, current_user.id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member of this group to post")

    new_post = models.Post(
        group_id=group_id,
        user_id=current_user.id,
        body=post.body,
        author=current_user,
    )
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)

    return new_post


# --- Phase 2: real-time layer ---

# Message history (the live feed itself comes over the websocket below)
@router.get("/{group_id}/messages", response_model=list[MessageResponse])
async def get_group_messages(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    offset: int = 0,
):
    result = await db.execute(
        select(models.Message)
        .options(selectinload(models.Message.author))
        .where(models.Message.group_id == group_id)
        .order_by(models.Message.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()


@router.websocket("/{group_id}/ws")
async def group_chat(
    websocket: WebSocket,
    group_id: int,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # browsers can't set custom headers on a WebSocket handshake, so the
    # token rides in as a query param instead of the usual Authorization header
    user_id = verify_access_token(token)
    if user_id is None:
        await websocket.close(code=4401)
        return

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        await websocket.close(code=4401)
        return

    result = await db.execute(select(models.User).where(models.User.id == user_id_int))
    user = result.scalars().first()
    if not user:
        await websocket.close(code=4401)
        return

    if not await _get_membership(group_id, user.id, db):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    manager.connect(group_id, websocket)
    try:
        while True:
            body = await websocket.receive_text()

            new_message = models.Message(group_id=group_id, user_id=user.id, body=body)
            db.add(new_message)
            await db.commit()
            await db.refresh(new_message)

            # SQLite drops tzinfo on read-back even though this was written as
            # UTC — same fix as schemas.UTCDatetime, applied by hand since this
            # payload is built manually rather than through a response model.
            created_at = new_message.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            await manager.broadcast(group_id, {
                "id": new_message.id,
                "group_id": group_id,
                "user_id": user.id,
                "username": user.username,
                "body": body,
                "created_at": created_at.isoformat(),
            })
    except WebSocketDisconnect:
        manager.disconnect(group_id, websocket)


# Audio rooms (LiveKit) — bookkeeping lives here, actual media never touches this server
@router.get("/{group_id}/audio-sessions/active", response_model=AudioSessionResponse)
async def get_active_audio_session(group_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.AudioSession).where(
            models.AudioSession.group_id == group_id,
            models.AudioSession.ended_at.is_(None),
        ),
    )
    session = result.scalars().first()
    if session:
        return session

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active audio session for this group")


@router.get("/{group_id}/audio-sessions", response_model=list[AudioSessionResponse])
async def get_audio_sessions(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
):
    result = await db.execute(
        select(models.AudioSession)
        .where(models.AudioSession.group_id == group_id)
        .order_by(models.AudioSession.started_at.desc())
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()


@router.post("/{group_id}/audio-sessions", response_model=AudioSessionResponse, status_code=status.HTTP_201_CREATED)
async def start_audio_session(
    group_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Group).where(models.Group.id == group_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    if not await _get_membership(group_id, current_user.id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member of this group")

    result = await db.execute(
        select(models.AudioSession).where(
            models.AudioSession.group_id == group_id,
            models.AudioSession.ended_at.is_(None),
        ),
    )
    existing_session = result.scalars().first()
    if existing_session:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An audio session is already active for this group")

    new_session = models.AudioSession(
        group_id=group_id,
        started_by=current_user.id,
        room_name=f"group-{group_id}-{uuid.uuid4().hex[:12]}",
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    return new_session


@router.post("/{group_id}/audio-sessions/{session_id}/join", response_model=LiveKitTokenResponse)
async def join_audio_session(
    group_id: int,
    session_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.AudioSession).where(
            models.AudioSession.id == session_id,
            models.AudioSession.group_id == group_id,
        ),
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio session not found")

    if session.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This audio session has ended")

    if not await _get_membership(group_id, current_user.id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member of this group")

    token = _build_livekit_token(session.room_name, current_user)
    return LiveKitTokenResponse(token=token, url=settings.livekit_url, room_name=session.room_name)


@router.post("/{group_id}/audio-sessions/{session_id}/end")
async def end_audio_session(
    group_id: int,
    session_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.AudioSession).where(
            models.AudioSession.id == session_id,
            models.AudioSession.group_id == group_id,
        ),
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio session not found")

    check_ownership(session.started_by, current_user, "Not authorized to end this audio session")

    if session.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Audio session already ended")

    session.ended_at = datetime.now(UTC)
    await db.commit()
    return {"message": "Audio session ended"}
