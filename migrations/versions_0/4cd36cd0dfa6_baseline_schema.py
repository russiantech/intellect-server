"""baseline schema

Revision ID: 4cd36cd0dfa6
Revises: 64d90fcdcba3
Create Date: 2026-05-12 18:25:19.240610

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cd36cd0dfa6'
down_revision: Union[str, None] = '64d90fcdcba3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
