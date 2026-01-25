import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from .connect import Base 

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    linked_folder_ids = Column(ARRAY(String), default=[])
    processed_filenames = Column(ARRAY(String), default=[])
    updated_at = Column(DateTime(timezone=True), server_default=func.now())