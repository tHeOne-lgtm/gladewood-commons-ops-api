"""CRUD routers for the legacy operations tables."""
from app import models, schemas
from app.crud import build_crud_router

properties = build_crud_router(
    prefix="/api/properties", tag="properties", entity="property",
    model=models.Property, schema_in=schemas.PropertyIn, schema_out=schemas.PropertyOut,
)
prospects = build_crud_router(
    prefix="/api/prospects", tag="prospects", entity="prospect",
    model=models.Prospect, schema_in=schemas.ProspectIn, schema_out=schemas.ProspectOut,
)
residents = build_crud_router(
    prefix="/api/residents", tag="residents", entity="resident",
    model=models.Resident, schema_in=schemas.ResidentIn, schema_out=schemas.ResidentOut,
)
conflict_log = build_crud_router(
    prefix="/api/conflict-log", tag="conflict-log", entity="conflict_entry",
    model=models.ConflictEntry, schema_in=schemas.ConflictEntryIn, schema_out=schemas.ConflictEntryOut,
)
