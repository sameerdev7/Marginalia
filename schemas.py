from datetime import date, datetime, UTC
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, ConfigDict, EmailStr


def _as_utc(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=UTC)


# SQLite has no timezone type, so every timestamp comes back from the ORM as a
# naive datetime — even though it was written with datetime.now(UTC). Without
# this, that naive value serializes with no offset ("...T11:15:12", no "Z"),
# and a browser's `new Date()` reads a bare ISO string as *local* time, not
# UTC — every relative timestamp in the app is then off by the client's UTC
# offset. Stamping UTC back on before serialization is correct precisely
# because everything here is written as UTC to begin with.
UTCDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr = Field(max_length=120)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=100)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=100)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar_url: str | None = None


class UserPrivate(UserPublic):
    email: EmailStr


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)


class Token(BaseModel):
    access_token: str
    token_type: str


class BookBase(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    author: str = Field(min_length=1, max_length=150)
    genre: str = Field(min_length=1, max_length=100)
    year: int
    cover_url: str | None = Field(default=None, max_length=500)
    pages: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=1000)


class BookCreate(BookBase):
    pass


class BookResponse(BookBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    owner: UserPublic


class SimilarBookResponse(BookResponse):
    similarity: float = Field(ge=0, le=1)


class ExternalBookResult(BaseModel):
    title: str
    author: str | None = None
    year: int | None = None
    cover_url: str | None = None
    pages: int | None = None


class BookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    author: str | None = Field(default=None, min_length=1, max_length=150)
    genre: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = None
    cover_url: str | None = Field(default=None, max_length=500)
    pages: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=1000)


ReadingStatus = Literal["want_to_read", "reading", "read", "dnf"]


class ReadingLogBase(BaseModel):
    status: ReadingStatus
    rating: float | None = Field(default=None, ge=1, le=5)
    review_text: str | None = Field(default=None, max_length=5000)
    started_at: date | None = None
    finished_at: date | None = None
    is_reread: bool = False


class ReadingLogCreate(ReadingLogBase):
    book_id: int


class ReadingLogResponse(ReadingLogBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    book_id: int
    created_at: UTCDatetime


class FriendsPopularItem(BaseModel):
    """A book that people you follow have been logging, with who and how many."""

    book: BookResponse
    readers: int
    friends: list[UserPublic]


class ReadingLogUpdate(BaseModel):
    status: ReadingStatus | None = None
    rating: float | None = Field(default=None, ge=1, le=5)
    review_text: str | None = Field(default=None, max_length=5000)
    started_at: date | None = None
    finished_at: date | None = None
    is_reread: bool | None = None


class CommentBase(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: int | None = None


class CommentCreate(CommentBase):
    pass


class CommentResponse(CommentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    log_id: int
    created_at: UTCDatetime
    author: UserPublic


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ReadingListBase(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    is_ranked: bool = False


class ReadingListCreate(ReadingListBase):
    pass


class ReadingListResponse(ReadingListBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: UTCDatetime


class ReadingListUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    is_ranked: bool | None = None


class ListItemBase(BaseModel):
    position: int
    note: str | None = Field(default=None, max_length=500)


class ListItemCreate(ListItemBase):
    book_id: int


class ListItemResponse(ListItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_id: int
    book_id: int
    book: BookResponse


class ListItemUpdate(BaseModel):
    position: int | None = None
    note: str | None = Field(default=None, max_length=500)


class GroupBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class GroupCreate(GroupBase):
    pass


class GroupResponse(GroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    created_at: UTCDatetime


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class GroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    role: str
    joined_at: UTCDatetime
    user: UserPublic


class PostBase(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class PostCreate(PostBase):
    pass


class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    user_id: int
    created_at: UTCDatetime
    author: UserPublic


class PostUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


# --- Phase 2: real-time layer ---


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    user_id: int
    body: str
    created_at: UTCDatetime
    author: UserPublic


class AudioSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    started_by: int
    room_name: str
    started_at: UTCDatetime
    ended_at: UTCDatetime | None


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
    room_name: str



# --- Journal ---


class JournalBookRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    cover_url: str | None = None


class JournalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    subtitle: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    cover_url: str | None = Field(default=None, max_length=500)
    book_id: int | None = None
    published: bool = False


class JournalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    subtitle: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=50000)
    cover_url: str | None = Field(default=None, max_length=500)
    book_id: int | None = None
    published: bool | None = None


class JournalSummary(BaseModel):
    """List-view shape: everything but the body."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subtitle: str | None = None
    excerpt: str
    cover_url: str | None = None
    published: bool
    reading_minutes: int
    created_at: UTCDatetime
    updated_at: UTCDatetime
    published_at: UTCDatetime | None = None
    author: UserPublic
    book: JournalBookRef | None = None


class JournalResponse(JournalSummary):
    body: str
