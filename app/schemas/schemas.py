"""
Backward-compat re-export of all schemas.
New code should import from individual domain modules.
"""
from app.schemas.auth import *
from app.schemas.users import *
from app.schemas.courses import *
from app.schemas.enrollments import *
from app.schemas.payments import *
from app.schemas.assessments import *
from app.schemas.social import *
from app.schemas.partnerships import *
from app.schemas.common import *
