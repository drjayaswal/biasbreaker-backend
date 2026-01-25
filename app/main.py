import re
import httpx
import uuid
from typing import List, Optional
from fastapi import Form, FastAPI, UploadFile, File, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from sqlalchemy.orm.attributes import flag_modified

# Internal Imports
from app.config import settings
from app.services.extract import extract_text
from app.db.model import User
from app.db.connect import init_db, get_db
from app.services.auth import (
    hash_password, 
    verify_password, 
    create_access_token, 
    decode_token
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting backend: Creating database tables...")
    init_db()
    yield
    print("Shutting down backend...")

app = FastAPI(lifespan=lifespan)
get_settings = settings()
security = HTTPBearer()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas ---
class ConnectData(BaseModel):
    email: str
    password: str

class FolderData(BaseModel):
    folderId: str
    description: str
    userId: str
    googleToken: str
    email: Optional[str] = None

# --- Auth Dependency ---
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security), 
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    
    user = db.query(User).filter(User.email == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found")
    return user

# --- Authentication Routes ---

@app.post("/connect")
async def connect(data: ConnectData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if user:
        if verify_password(data.password, user.hashed_password):
            token = create_access_token(data={"sub": user.email})
            return {
                "success": True, 
                "token": token,
                "email": user.email,
                "id": str(user.id)
            }
        raise HTTPException(status_code=401, detail="Incorrect password")
    
    # Create new user if not exists
    new_user = User(
        email=data.email, 
        hashed_password=hash_password(data.password),
        linked_folder_ids=[],
        processed_filenames=[]
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    token = create_access_token(data={"sub": new_user.email})
    return {
        "success": True,
        "token": token,
        "email": new_user.email,
        "id": str(new_user.id)
    }

@app.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"email": current_user.email, "id": str(current_user.id), "authenticated": True}

# --- Core Logic Routes ---

@app.post("/get-folder")
async def get_folder(
    request_data: FolderData, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    results = []
    filenames_to_save = []

    async with httpx.AsyncClient() as client:
        # 1. Fetch files from Google Drive folder
        drive_url = f"https://www.googleapis.com/drive/v3/files?q='{request_data.folderId}'+in+parents+and+trashed=false"
        drive_resp = await client.get(
            drive_url, 
            headers={"Authorization": f"Bearer {request_data.googleToken}"}
        )
        files = drive_resp.json().get("files", [])

        for drive_file in files:
            file_id = drive_file["id"]
            filename = drive_file["name"]
            mime_type = drive_file.get("mimeType", "text/plain")
            
            # 2. Download content from Drive
            download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            file_content_resp = await client.get(
                download_url, 
                headers={"Authorization": f"Bearer {request_data.googleToken}"}
            )
            
            if file_content_resp.status_code == 200:
                # 3. Process and analyze
                raw_text = extract_text(file_content_resp.content, mime_type)
                words = re.findall(r'\b\w+\b', raw_text.lower())

                ml_resp = await client.post(
                    f"{get_settings.ML_SERVER_URL}/analyze", 
                    json={
                        "filename": filename, 
                        "words": words, 
                        "description": request_data.description
                    },
                    timeout=60.0
                )
                results.append({"filename": filename, "ml_analysis": ml_resp.json()})
                filenames_to_save.append(filename)

    # Update User History
    current_user.processed_filenames = (list(current_user.processed_filenames or []) + filenames_to_save)[-100:]
    flag_modified(current_user, "processed_filenames")
    db.commit()
    
    return results

@app.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...), 
    description: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    results = []
    filenames_to_save = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for file in files:
            content = await file.read()
            raw_text = extract_text(content, file.content_type)
            words = re.findall(r'\b\w+\b', raw_text.lower())

            try:
                ml_resp = await client.post(
                    f"{get_settings.ML_SERVER_URL}/analyze", 
                    json={
                        "filename": file.filename, 
                        "words": words, 
                        "description": description
                    },
                    timeout=60.0
                )
                ml_data = ml_resp.json()
            except Exception as e:
                ml_data = {"error": "ML Analysis failed", "details": str(e)}

            results.append({"filename": file.filename, "ml_analysis": ml_data})
            filenames_to_save.append(file.filename)

    # Track only filenames in DB (PostgreSQL Array)
    current_user.processed_filenames = (list(current_user.processed_filenames or []) + filenames_to_save)[-100:]
    flag_modified(current_user, "processed_filenames")
    db.commit()
    
    return results