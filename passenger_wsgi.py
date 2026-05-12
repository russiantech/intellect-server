import sys
import os

INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# For Passenger ASGI mode (if supported)
import uvicorn
from main import app

# This creates a WSGI-compatible entry that starts uvicorn
class UvicornWrapper:
    def __init__(self, app):
        self.app = app
    
    def __call__(self, environ, start_response):
        # Delegate to uvicorn's internal WSGI adapter
        # This only works if Passenger supports long-running processes
        pass

# Fallback: use uvicorn's built-in WSGI middleware
from uvicorn.middleware.wsgi import WSGIMiddleware
application = WSGIMiddleware(app)

