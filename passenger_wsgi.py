# import sys
# import os

# # Add project to path
# INTERP = os.path.expanduser("~/fastapi_app/venv/bin/python")
# if sys.executable != INTERP:
#     os.execl(INTERP, INTERP, *sys.argv)

# from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# # Import your app
# from main import app as application

# # Add proxy headers middleware (critical for HTTPS behind Apache)
# application.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


# v2 - interpreter path updated to match cpanel's python env path
import sys
import os

# Add project to path
INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Import your app
from main import app as application

# Add proxy headers middleware (critical for HTTPS behind Apache)
application.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
