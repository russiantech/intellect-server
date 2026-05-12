from fastapi.responses import JSONResponse
from datetime import datetime
from pydantic import BaseModel
from fastapi.encoders import jsonable_encoder
from typing import Any, Callable, List, Optional, Union
from fastapi import Request


# ============================================================================
# API RESPONSE HELPER
# ============================================================================

def api_response(
    success: bool, 
    message: str, 
    data=None, 
    errors=None, 
    status_code: int = None, 
    path: str = None
):
    """
    Centralized API response helper.
    Ensures consistent JSON response format across all endpoints.
    """
    if status_code is None:
        status_code = 200 if success else 400

    # Handle both Pydantic models and lists of them
    if isinstance(data, BaseModel):
        data = data.model_dump()
    elif isinstance(data, list) and data and isinstance(data[0], BaseModel):
        data = [d.model_dump() for d in data]

    payload = {
        "success": success,
        "message": message,
        "timestamp": datetime.now().isoformat() + "Z",
    }

    if path:
        payload["path"] = path
    if data is not None:
        payload["data"] = jsonable_encoder(data)
    if errors is not None:
        payload["errors"] = errors

    return JSONResponse(content=payload, status_code=status_code)


# ============================================================================
# PAGE SERIALIZER
# ============================================================================

class PageMeta(BaseModel):
    """Metadata for paginated responses."""
    total_items_count: int
    offset: int
    requested_page_size: int
    current_page_number: int
    total_pages_count: int
    has_next_page: bool
    has_prev_page: bool
    next_page_url: Optional[str] = None
    prev_page_url: Optional[str] = None


class PageSerializer:
    """
    Universal FastAPI PageSerializer with automatic summary detection.
    """

    def __init__(
        self,
        request: Request,
        obj: Optional[Any] = None,
        resource_name: str = "items",
        summary_func: Optional[Callable[[Any], dict]] = None,
        context_key: Optional[str] = None,
        context_id: Optional[Union[str, int]] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ):
        self.request = request
        self.resource_name = resource_name
        self.context_key = context_key
        self.context_id = context_id
        self.summary_func = summary_func or self._auto_summary
        self.data: dict = {}
        self.items: List[dict] = []

        if obj is None:
            obj = []

        if self._is_paginated(obj):
            self._serialize_pagination(obj)
        elif isinstance(obj, list):
            self._serialize_items(obj, page=page, page_size=page_size)
        else:
            self._serialize_items([obj], page=page, page_size=page_size)

    def _auto_summary(self, item: Any) -> dict:
        """
        Automatically choose the best serialization strategy:
        - ORM with `get_summary()`
        - Pydantic model with `.model_dump()`
        - ORM with `.to_dict()`
        - Fallback to `__dict__`
        """
        if hasattr(item, "get_summary") and callable(item.get_summary):
            return item.get_summary()
        if isinstance(item, BaseModel):
            return item.model_dump()
        if hasattr(item, "to_dict") and callable(item.to_dict):
            return item.to_dict()
        if isinstance(item, dict):
            return item
        return item.__dict__ if hasattr(item, "__dict__") else item

    @staticmethod
    def _is_paginated(obj: Any) -> bool:
        """
        Detects common SQLAlchemy paginate() objects
        """
        return all(
            hasattr(obj, attr) 
            for attr in ["items", "page", "per_page", "total", "pages", "has_next", "has_prev"]
        )

    def _serialize_pagination(self, pagination_obj: Any):
        """Serialize SQLAlchemy pagination object."""
        self.items = [self.summary_func(i) for i in pagination_obj.items]

        current_page = pagination_obj.page
        per_page = pagination_obj.per_page
        total = pagination_obj.total
        pages = pagination_obj.pages

        base_params = {
            "page_size": per_page,
            **self.request.path_params,
        }
        if self.context_key and self.context_id:
            base_params[self.context_key] = self.context_id

        def build_url(page):
            params = {**base_params, 'page': page}
            query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
            return f"{self.request.url.path}?{query_string}"

        next_url = build_url(current_page + 1) if pagination_obj.has_next else None
        prev_url = build_url(current_page - 1) if pagination_obj.has_prev else None

        self.data = PageMeta(
            total_items_count=total,
            offset=(current_page - 1) * per_page,
            requested_page_size=per_page,
            current_page_number=current_page,
            total_pages_count=pages,
            has_next_page=pagination_obj.has_next,
            has_prev_page=pagination_obj.has_prev,
            next_page_url=next_url,
            prev_page_url=prev_url
        ).model_dump()

    def _serialize_items(self, items: list, page: Optional[int] = None, page_size: Optional[int] = None):
        """Serialize a list of items with manual pagination metadata."""
        self.items = [self.summary_func(i) for i in items]

        # Default to page 1 if not provided
        current_page = page if page is not None else 1
        
        # Default to total items count if page_size not provided
        requested_size = page_size if page_size is not None else len(items)
        
        # Calculate total pages
        total_items = len(items)
        total_pages = max(1, (total_items + requested_size - 1) // requested_size) if requested_size > 0 else 1
        
        # Calculate offset
        offset = (current_page - 1) * requested_size if requested_size > 0 else 0
        
        # Determine if there are next/prev pages
        has_next = current_page < total_pages
        has_prev = current_page > 1

        # Build URLs for next/prev pages
        base_params = {
            "page_size": requested_size,
            **self.request.path_params,
        }
        if self.context_key and self.context_id:
            base_params[self.context_key] = self.context_id

        def build_url(page_num):
            params = {**base_params, 'page': page_num}
            query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
            return f"{self.request.url.path}?{query_string}"

        next_url = build_url(current_page + 1) if has_next else None
        prev_url = build_url(current_page - 1) if has_prev else None

        self.data = PageMeta(
            total_items_count=total_items,
            offset=offset,
            requested_page_size=requested_size,
            current_page_number=current_page,
            total_pages_count=total_pages,
            has_next_page=has_next,
            has_prev_page=has_prev,
            next_page_url=next_url,
            prev_page_url=prev_url
        ).model_dump()

    def get_response(self, message: str = "Data fetched successfully"):
        """
        Return a standard FastAPI JSON response.
        """
        return api_response(
            success=True,
            message=message,
            data={
                "page_meta": self.data,
                self.resource_name: self.items
            }
        )

