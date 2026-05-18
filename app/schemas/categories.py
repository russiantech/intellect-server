  
from typing import Optional
from pydantic import BaseModel, Field

# ── Category & Tag ────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    title: str = Field(..., max_length=100)
    description: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    sort_order:  int = 0


class CategoryUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None


class CategoryOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    slug: Optional[str] = None

    class Config:
        from_attributes = True

