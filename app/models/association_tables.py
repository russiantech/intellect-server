"""
association_tables.py — Pure join tables (no ORM classes needed).

All tables use the shared metadata from Base so Alembic/create_all picks them up.
"""

from sqlalchemy import Boolean, DateTime, Table, Column, Integer, ForeignKey
from app.db.database import Base
# ── User ↔ Role (many-to-many) ─────────────────────────────────────────────
# ─────────────────────────────────────────────
#  ASSOCIATION TABLES
# ─────────────────────────────────────────────

from app.db.database import Base


user_role_assoc = Table(
    "user_role_assoc", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)

course_tag_assoc = Table(
    "course_tag_assoc", Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)

course_category_assoc = Table(
    "course_category_assoc", Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("category_id", Integer, ForeignKey("categories.id"), primary_key=True),
)

# 
path_category_assoc = Table(
      "path_category_assoc",
      Base.metadata,
      Column("path_id",     Integer, ForeignKey("learning_paths.id"), primary_key=True),
      Column("category_id", Integer, ForeignKey("categories.id"),     primary_key=True),
  )

path_course_assoc = Table(
    "path_course_assoc", Base.metadata,
    Column("path_id", Integer, ForeignKey("learning_paths.id"), primary_key=True),
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("order_index", Integer, default=0),
)

user_topic_progress = Table(
    "user_topic_progress", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("topic_id", Integer, ForeignKey("topics.id"), primary_key=True),
    Column("completed", Boolean, default=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

partner_course_assoc = Table(
    "partner_course_assoc", Base.metadata,
    Column("partnership_id", Integer, ForeignKey("partnerships.id"), primary_key=True),
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
)

partner_path_assoc = Table(
    "partner_path_assoc", Base.metadata,
    Column("partnership_id", Integer, ForeignKey("partnerships.id"), primary_key=True),
    Column("path_id", Integer, ForeignKey("learning_paths.id"), primary_key=True),
)





