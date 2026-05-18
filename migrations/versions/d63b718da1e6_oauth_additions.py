"""oauth additions

Revision ID: d63b718da1e6
Revises: 2919a82682d2
Create Date: 2026-05-18 02:08:15.443729

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd63b718da1e6'
down_revision: Union[str, None] = '2919a82682d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
