"""
CRUD Route Factory for Orderbot Admin API
==========================================

This module provides a factory for generating standard CRUD (Create, Read, Update, Delete)
routes for SQLAlchemy models. It consolidates common patterns used across admin routes
to reduce code duplication and ensure consistent behavior.

Features:
---------
- Standard CRUD endpoints (list, create, get, update, delete)
- Configurable uniqueness validation
- Custom query ordering
- Pre-delete validation hooks
- Custom response transformation
- Logging for all mutations

Usage:
------
    from .crud_factory import CRUDRouterFactory

    crud = CRUDRouterFactory(
        model=Category,
        create_schema=CategoryCreate,
        update_schema=CategoryUpdate,
        response_schema=CategoryOut,
        prefix="/admin/categories",
        tags=["Admin - Categories"],
        id_param="category_id",
        not_found_message="Category not found",
        unique_fields=["slug"],
        order_by=["name"],
    )
    router = crud.router
"""

import logging
from typing import Any, Callable, Generic, TypeVar, Sequence

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db


# Type variables for generic model and schema types
ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ResponseSchemaType = TypeVar("ResponseSchemaType", bound=BaseModel)
ListResponseType = TypeVar("ListResponseType", bound=BaseModel)


class CRUDRouterFactory(Generic[ModelType, CreateSchemaType, UpdateSchemaType, ResponseSchemaType]):
    """
    Factory for generating standard CRUD routes.

    This class creates a FastAPI router with standard CRUD endpoints for a given
    SQLAlchemy model and Pydantic schemas.

    Type Parameters:
        ModelType: The SQLAlchemy model class
        CreateSchemaType: Pydantic schema for create requests
        UpdateSchemaType: Pydantic schema for update requests
        ResponseSchemaType: Pydantic schema for responses

    Attributes:
        router: The configured FastAPI APIRouter instance

    Example:
        crud = CRUDRouterFactory(
            model=Category,
            create_schema=CategoryCreate,
            update_schema=CategoryUpdate,
            response_schema=CategoryOut,
            prefix="/admin/categories",
            tags=["Admin - Categories"],
        )
        # Register with FastAPI app
        app.include_router(crud.router)
    """

    def __init__(
        self,
        *,
        model: type[ModelType],
        create_schema: type[CreateSchemaType],
        update_schema: type[UpdateSchemaType],
        response_schema: type[ResponseSchemaType],
        prefix: str,
        tags: list[str],
        id_param: str = "id",
        not_found_message: str = "Resource not found",
        unique_fields: list[str] | None = None,
        order_by: list[str] | None = None,
        # Optional callbacks for customization
        to_response: Callable[[ModelType, Session], ResponseSchemaType] | None = None,
        on_before_create: Callable[[CreateSchemaType, Session], dict[str, Any]] | None = None,
        on_create_pre_commit: Callable[[ModelType, CreateSchemaType, Session], None] | None = None,
        on_after_create: Callable[[ModelType, Session], None] | None = None,
        on_before_update: Callable[[ModelType, UpdateSchemaType, Session], None] | None = None,
        on_after_update: Callable[[ModelType, Session], None] | None = None,
        on_before_delete: Callable[[ModelType, Session], None] | None = None,
        list_response_schema: type[ListResponseType] | None = None,
        list_response_builder: Callable[[list[ResponseSchemaType], int], ListResponseType] | None = None,
    ):
        """
        Initialize the CRUD router factory.

        Args:
            model: SQLAlchemy model class
            create_schema: Pydantic schema for create requests
            update_schema: Pydantic schema for update requests
            response_schema: Pydantic schema for individual item responses
            prefix: URL prefix for all routes (e.g., "/admin/categories")
            tags: OpenAPI tags for route grouping
            id_param: Name of the ID path parameter (default: "id")
            not_found_message: Error message when item not found
            unique_fields: List of field names that must be unique
            order_by: List of field names to order results by
            to_response: Custom function to convert model to response schema.
                         If None, uses response_schema.model_validate(item)
            on_before_create: Hook called before creating. Returns dict of model kwargs.
                              If None, uses payload.model_dump()
            on_create_pre_commit: Hook called after flush (item has ID) but before commit.
                                  Use for child records like aliases.
            on_after_create: Hook called after creating and committing
            on_before_update: Hook called before updating. Can modify item in place.
            on_after_update: Hook called after updating and committing
            on_before_delete: Hook called before deleting. Raise HTTPException to prevent.
            list_response_schema: Schema for list endpoint if different from List[response_schema]
            list_response_builder: Function to build list response from items and total
        """
        self.model = model
        self.create_schema = create_schema
        self.update_schema = update_schema
        self.response_schema = response_schema
        self.id_param = id_param
        self.not_found_message = not_found_message
        self.unique_fields = unique_fields or []
        self.order_by = order_by or []
        self.to_response = to_response
        self.on_before_create = on_before_create
        self.on_create_pre_commit = on_create_pre_commit
        self.on_after_create = on_after_create
        self.on_before_update = on_before_update
        self.on_after_update = on_after_update
        self.on_before_delete = on_before_delete
        self.list_response_schema = list_response_schema
        self.list_response_builder = list_response_builder

        self.logger = logging.getLogger(f"{__name__}.{model.__name__}")

        self.router = APIRouter(prefix=prefix, tags=tags)
        self._register_routes()

    def _get_model_name(self) -> str:
        """Get a human-readable name for the model."""
        return self.model.__name__

    def _model_to_response(self, item: ModelType, db: Session) -> ResponseSchemaType:
        """Convert a model instance to its response schema."""
        if self.to_response:
            return self.to_response(item, db)
        return self.response_schema.model_validate(item)

    def _check_unique_fields(
        self,
        db: Session,
        payload: BaseModel,
        exclude_id: int | None = None,
    ) -> None:
        """
        Check that unique fields don't conflict with existing records.

        Args:
            db: Database session
            payload: The create/update payload
            exclude_id: ID to exclude from uniqueness check (for updates)

        Raises:
            HTTPException: If a unique field value already exists
        """
        for field in self.unique_fields:
            value = getattr(payload, field, None)
            if value is None:
                continue

            # Normalize string values
            if isinstance(value, str):
                value = value.lower().strip()

            query = db.query(self.model).filter(
                getattr(self.model, field) == value
            )
            if exclude_id is not None:
                query = query.filter(self.model.id != exclude_id)

            existing = query.first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"A {self._get_model_name().lower()} with {field} '{value}' already exists"
                )

    def _build_order_by(self) -> list:
        """Build SQLAlchemy order_by clause from configuration."""
        return [getattr(self.model, field) for field in self.order_by]

    def _register_routes(self) -> None:
        """Register all CRUD routes on the router."""
        self._register_list()
        self._register_create()
        self._register_get()
        self._register_update()
        self._register_delete()

    def _register_list(self) -> None:
        """Register the list endpoint."""
        # Determine response model
        if self.list_response_schema:
            response_model = self.list_response_schema
        else:
            response_model = list[self.response_schema]

        @self.router.get("", response_model=response_model)
        def list_items(
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
        ):
            query = db.query(self.model)

            # Apply ordering
            if self.order_by:
                query = query.order_by(*self._build_order_by())

            items = query.all()
            response_items = [self._model_to_response(item, db) for item in items]

            if self.list_response_builder:
                return self.list_response_builder(response_items, len(items))

            return response_items

    def _register_create(self) -> None:
        """Register the create endpoint."""
        @self.router.post("", response_model=self.response_schema, status_code=201)
        def create_item(
            payload: self.create_schema,
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
        ):
            # Check uniqueness constraints
            self._check_unique_fields(db, payload)

            # Build model kwargs
            if self.on_before_create:
                model_kwargs = self.on_before_create(payload, db)
            else:
                model_kwargs = payload.model_dump()

            # Create and persist
            item = self.model(**model_kwargs)
            db.add(item)

            # Flush to get the ID before commit (needed for child records)
            if self.on_create_pre_commit:
                db.flush()
                self.on_create_pre_commit(item, payload, db)

            db.commit()
            db.refresh(item)

            if self.on_after_create:
                self.on_after_create(item, db)

            self.logger.info(
                "Created %s: id=%d",
                self._get_model_name().lower(),
                item.id
            )

            return self._model_to_response(item, db)

    def _register_get(self) -> None:
        """Register the get-by-id endpoint."""
        # We need to create the route with the configured id_param
        path = "/{" + self.id_param + "}"

        @self.router.get(path, response_model=self.response_schema)
        def get_item(
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
            **kwargs,
        ):
            item_id = kwargs.get(self.id_param)
            item = db.query(self.model).filter(self.model.id == item_id).first()

            if not item:
                raise HTTPException(status_code=404, detail=self.not_found_message)

            return self._model_to_response(item, db)

        # FastAPI needs explicit path params - recreate the route properly
        self.router.routes.pop()  # Remove the incorrectly registered route

        # Register with explicit path parameter
        self.router.add_api_route(
            path,
            self._make_get_handler(),
            methods=["GET"],
            response_model=self.response_schema,
        )

    def _make_get_handler(self) -> Callable:
        """Create the get handler with proper signature."""
        model = self.model
        not_found_message = self.not_found_message
        to_response = self._model_to_response

        async def get_item(
            item_id: int,
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
        ):
            item = db.query(model).filter(model.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=not_found_message)
            return to_response(item, db)

        # Rename parameter to match id_param
        import inspect
        sig = inspect.signature(get_item)
        new_params = []
        for name, param in sig.parameters.items():
            if name == "item_id":
                new_params.append(param.replace(name=self.id_param))
            else:
                new_params.append(param)
        get_item.__signature__ = sig.replace(parameters=new_params)

        return get_item

    def _register_update(self) -> None:
        """Register the update endpoint."""
        path = "/{" + self.id_param + "}"

        self.router.add_api_route(
            path,
            self._make_update_handler(),
            methods=["PUT"],
            response_model=self.response_schema,
        )

    def _make_update_handler(self) -> Callable:
        """Create the update handler with proper signature."""
        model = self.model
        update_schema = self.update_schema
        not_found_message = self.not_found_message
        unique_fields = self.unique_fields
        check_unique = self._check_unique_fields
        on_before_update = self.on_before_update
        on_after_update = self.on_after_update
        to_response = self._model_to_response
        logger = self.logger
        model_name = self._get_model_name()

        async def update_item(
            item_id: int,
            payload: update_schema,
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
        ):
            item = db.query(model).filter(model.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=not_found_message)

            # Check uniqueness for fields being updated
            for field in unique_fields:
                new_value = getattr(payload, field, None)
                if new_value is not None:
                    current_value = getattr(item, field, None)
                    # Normalize for comparison
                    if isinstance(new_value, str):
                        new_value = new_value.lower().strip()
                    if isinstance(current_value, str):
                        current_value = current_value.lower().strip()
                    # Only check if value is actually changing
                    if new_value != current_value:
                        check_unique(db, payload, exclude_id=item_id)
                        break

            # Call before hook - if provided, it handles all field updates
            if on_before_update:
                on_before_update(item, payload, db)
            else:
                # Default: apply updates from payload
                update_data = payload.model_dump(exclude_unset=True)
                for field, value in update_data.items():
                    if hasattr(item, field):
                        # Normalize string values for unique fields
                        if field in unique_fields and isinstance(value, str):
                            value = value.lower().strip()
                        setattr(item, field, value)

            db.commit()
            db.refresh(item)

            if on_after_update:
                on_after_update(item, db)

            logger.info(
                "Updated %s: id=%d",
                model_name.lower(),
                item.id
            )

            return to_response(item, db)

        # Rename parameter to match id_param
        import inspect
        sig = inspect.signature(update_item)
        new_params = []
        for name, param in sig.parameters.items():
            if name == "item_id":
                new_params.append(param.replace(name=self.id_param))
            else:
                new_params.append(param)
        update_item.__signature__ = sig.replace(parameters=new_params)

        return update_item

    def _register_delete(self) -> None:
        """Register the delete endpoint."""
        path = "/{" + self.id_param + "}"

        self.router.add_api_route(
            path,
            self._make_delete_handler(),
            methods=["DELETE"],
            status_code=204,
        )

    def _make_delete_handler(self) -> Callable:
        """Create the delete handler with proper signature."""
        model = self.model
        not_found_message = self.not_found_message
        on_before_delete = self.on_before_delete
        logger = self.logger
        model_name = self._get_model_name()

        async def delete_item(
            item_id: int,
            db: Session = Depends(get_db),
            _admin: str = Depends(verify_admin_credentials),
        ):
            item = db.query(model).filter(model.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=not_found_message)

            if on_before_delete:
                on_before_delete(item, db)

            logger.info(
                "Deleting %s: id=%d",
                model_name.lower(),
                item.id
            )

            db.delete(item)
            db.commit()
            return None

        # Rename parameter to match id_param
        import inspect
        sig = inspect.signature(delete_item)
        new_params = []
        for name, param in sig.parameters.items():
            if name == "item_id":
                new_params.append(param.replace(name=self.id_param))
            else:
                new_params.append(param)
        delete_item.__signature__ = sig.replace(parameters=new_params)

        return delete_item
