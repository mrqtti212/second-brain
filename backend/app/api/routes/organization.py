import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.category import Category
from app.models.project import Project
from app.models.tag import Tag
from app.schemas import organization as s
from app.services import organization as service


def build_router(prefix, label, model, create_schema, update_schema, read_schema) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[label])

    @router.get("", response_model=list[read_schema])
    def list_items(db: Session = Depends(get_db)):
        return service.list_items(db, model)

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    def create_item(data: create_schema, db: Session = Depends(get_db)):
        return service.create_item(db, model, data)

    @router.get("/{item_id}", response_model=read_schema)
    def get_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
        return service.get_item(db, model, item_id)

    @router.patch("/{item_id}", response_model=read_schema)
    def update_item(item_id: uuid.UUID, data: update_schema, db: Session = Depends(get_db)):
        return service.update_item(db, model, item_id, data)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
        service.delete_item(db, model, item_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


categories = build_router(
    "/categories", "categories", Category, s.CategoryCreate, s.CategoryUpdate, s.CategoryRead
)
projects = build_router(
    "/projects", "projects", Project, s.ProjectCreate, s.ProjectUpdate, s.ProjectRead
)
tags = build_router("/tags", "tags", Tag, s.TagCreate, s.TagUpdate, s.TagRead)
