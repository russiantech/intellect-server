"""baseline schema

Revision ID: a2db87551971
Revises: 4cd36cd0dfa6
Create Date: 2026-05-12 18:26:22.355981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2db87551971'
down_revision: Union[str, None] = '4cd36cd0dfa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
