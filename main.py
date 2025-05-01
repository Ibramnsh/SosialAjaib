import os
import shutil
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
import models
from database import engine, SessionLocal
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

# Create directories if they don't exist
os.makedirs("static/uploads", exist_ok=True)

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates with custom filters
templates = Jinja2Templates(directory="templates")

# Define the now filter function
def now_filter(format_string):
    return datetime.now().strftime(format_string)

# Add the filter to Jinja2 environment
# This is the correct way to add filters in FastAPI/Starlette
templates.env.filters["now"] = now_filter

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# User authentication
def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    # Pass the current year directly to the template
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "current_year": current_year})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse("register.html", {"request": request, "current_year": current_year})

@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if username already exists
    user_exists = db.query(models.User).filter(models.User.username == username).first()
    if user_exists:
        current_year = datetime.now().strftime("%Y")
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": "Username already exists", "current_year": current_year}
        )
    
    # Hash the password
    hashed_password = pwd_context.hash(password)
    
    # Create new user
    new_user = models.User(
        username=username,
        password=hashed_password,
        email=email,
        is_admin=(username == "admin")  # Make user admin if username is 'admin'
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Set session
    request.session["user_id"] = new_user.id
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse("login.html", {"request": request, "current_year": current_year})

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Find user
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not pwd_context.verify(password, user.password):
        current_year = datetime.now().strftime("%Y")
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Invalid username or password", "current_year": current_year}
        )
    
    # Set session
    request.session["user_id"] = user.id
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("user_id", None)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/create-post", response_class=HTMLResponse)
async def create_post_page(
    request: Request, 
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse("create_post.html", {"request": request, "user": user, "current_year": current_year})

@app.post("/create-post")
async def create_post(
    request: Request,
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Handle image upload
    image_path = None
    if image and image.filename:
        # Create a unique filename
        file_extension = os.path.splitext(image.filename)[1]
        unique_filename = f"{user.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_extension}"
        image_path = f"uploads/{unique_filename}"
        
        # Save the file
        with open(f"static/{image_path}", "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    
    # Create post
    new_post = models.Post(
        content=content,
        image_path=image_path,
        user_id=user.id,
        timestamp=datetime.now()
    )
    db.add(new_post)
    db.commit()
    
    return RedirectResponse(url=f"/profile/{user.username}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/profile/{username}", response_class=HTMLResponse)
async def profile(
    request: Request,
    username: str,
    db: Session = Depends(get_db)
):
    # Get profile user
    profile_user = db.query(models.User).filter(models.User.username == username).first()
    if not profile_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get current user
    current_user = get_current_user(request, db)
    
    # Get posts
    posts = db.query(models.Post).filter(models.Post.user_id == profile_user.id).order_by(models.Post.timestamp.desc()).all()
    
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse(
        "profile.html", 
        {
            "request": request, 
            "profile_user": profile_user, 
            "user": current_user,
            "posts": posts,
            "is_own_profile": current_user and current_user.id == profile_user.id,
            "current_year": current_year
        }
    )

@app.get("/edit-post/{post_id}", response_class=HTMLResponse)
async def edit_post_page(
    request: Request,
    post_id: int,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Check if user owns the post or is admin
    if post.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to edit this post")
    
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse(
        "edit_post.html", 
        {"request": request, "user": user, "post": post, "current_year": current_year}
    )

@app.post("/edit-post/{post_id}")
async def edit_post(
    request: Request,
    post_id: int,
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Check if user owns the post or is admin
    if post.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to edit this post")
    
    # Update content
    post.content = content
    
    # Handle image upload if provided
    if image and image.filename:
        # Delete old image if exists
        if post.image_path:
            old_image_path = f"static/{post.image_path}"
            if os.path.exists(old_image_path):
                os.remove(old_image_path)
        
        # Create a unique filename
        file_extension = os.path.splitext(image.filename)[1]
        unique_filename = f"{user.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_extension}"
        image_path = f"uploads/{unique_filename}"
        
        # Save the file
        with open(f"static/{image_path}", "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        
        post.image_path = image_path
    
    db.commit()
    
    # Redirect to profile of post owner
    post_owner = db.query(models.User).filter(models.User.id == post.user_id).first()
    return RedirectResponse(
        url=f"/profile/{post_owner.username}", 
        status_code=status.HTTP_303_SEE_OTHER
    )

@app.get("/delete-post/{post_id}")
async def delete_post(
    request: Request,
    post_id: int,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Check if user owns the post or is admin
    if post.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")
    
    # Delete image if exists
    if post.image_path:
        image_path = f"static/{post.image_path}"
        if os.path.exists(image_path):
            os.remove(image_path)
    
    # Delete post
    db.delete(post)
    db.commit()
    
    # Redirect to profile or admin dashboard
    if user.is_admin and post.user_id != user.id:
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return RedirectResponse(url=f"/profile/{user.username}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    
    results = []
    if q:
        # Search for users
        users = db.query(models.User).filter(models.User.username.contains(q)).all()
        
        # Search for posts
        posts = db.query(models.Post).filter(models.Post.content.contains(q)).all()
        
        results = {
            "users": users,
            "posts": posts
        }
    
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse(
        "search.html", 
        {"request": request, "user": user, "query": q, "results": results, "current_year": current_year}
    )

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    # Get all users
    users = db.query(models.User).all()
    
    # Get all posts
    posts = db.query(models.Post).order_by(models.Post.timestamp.desc()).all()
    
    # Get usernames for posts
    post_data = []
    for post in posts:
        post_owner = db.query(models.User).filter(models.User.id == post.user_id).first()
        post_data.append({
            "post": post,
            "username": post_owner.username if post_owner else "Unknown"
        })
    
    current_year = datetime.now().strftime("%Y")
    return templates.TemplateResponse(
        "admin_dashboard.html", 
        {"request": request, "user": user, "users": users, "post_data": post_data, "current_year": current_year}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
