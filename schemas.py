from pydantic import BaseModel, Field, ConfigDict, EmailStr

class UserBase(BaseModel):
        username: str = Field(min_length=1, max_length=50)
        email: EmailStr = Field(max_length=120)

class UserCreate(UserBase):
        pass 

class UserResponse(UserBase):
        model_config = ConfigDict(from_attributes=True)
        
        id: int
        
class UserUpdate(BaseModel):
        username: str | None = Field(default=None, min_length=1, max_length=100)
        email: EmailStr | None = Field(default=None, max_length=100)
        
        
class BookBase(BaseModel):
        title: str = Field(min_length=1, max_length=150)
        author: str = Field(min_length=1, max_length=150)
        genre: str = Field(min_length=1, max_length=100)
        year: int
        rating: float = Field(ge=1, le=5)
        pages: int = Field(gt=0)
        description: str = Field(min_length=1, max_length=1000)  
        
class BookCreate(BookBase):
        user_id: int # temporary

class BookResponse(BookBase):
        model_config = ConfigDict(from_attributes=True)
        
        id: int      
        user_id: int    
        
        
class BookUpdate(BaseModel):
        title: str | None = Field(default=None, min_length=1, max_length=150)
        author: str | None = Field(default=None, min_length=1, max_length=150)
        genre: str | None = Field(default=None, min_length=1, max_length=100)
        year: int | None = None
        rating: float | None = Field(default=None, ge=1, le=5)
        pages: int | None = Field(default=None, gt=0)
        description: str | None = Field(default=None,min_length=1, max_length=1000)  