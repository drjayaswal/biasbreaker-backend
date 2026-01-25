from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class FolderLinkRequest(BaseModel):
    folderId: str
    userId: UUID
    email: Optional[EmailStr] = None

class UserResponse(UserBase):
    id: UUID
    linked_folder_ids: List[str] = []
    processed_filenames: List[str] = []
    updated_at: datetime

    class Config:
        from_attributes = True

class LatestFolderResponse(BaseModel):
    latest_folder_id: Optional[str] = None