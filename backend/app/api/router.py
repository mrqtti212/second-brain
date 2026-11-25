from fastapi import APIRouter

from app.api.routes import documents, health, notes, organization, search

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(notes.router)
api_router.include_router(documents.router)
api_router.include_router(organization.categories)
api_router.include_router(organization.projects)
api_router.include_router(organization.tags)
api_router.include_router(search.router)
