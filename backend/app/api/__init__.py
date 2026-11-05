from fastapi import APIRouter

from app.api import client, projects, proposals, system

api_router = APIRouter(prefix="/api")
api_router.include_router(projects.router)
api_router.include_router(proposals.router)
api_router.include_router(client.router)
api_router.include_router(system.router)
