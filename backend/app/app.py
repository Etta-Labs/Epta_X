from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# Mount frontend static files and config
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/config", StaticFiles(directory="frontend/config"), name="config")
app.mount("/pages", StaticFiles(directory="frontend/pages"), name="pages")


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("frontend/pages/landing.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return FileResponse("frontend/pages/index.html")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "ETTA-X API is running"}