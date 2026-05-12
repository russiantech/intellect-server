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


# # v2 - interpreter path updated to match cpanel's python env path
# import sys
# import os

# # Add project to path
# INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
# if sys.executable != INTERP:
#     os.execl(INTERP, INTERP, *sys.argv)

# from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# # Import your app
# from main import app as application

# # Add proxy headers middleware (critical for HTTPS behind Apache)
# application.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")



# v3
# import sys
# import os

# INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
# if sys.executable != INTERP:
#     os.execl(INTERP, INTERP, *sys.argv)

# # ASGI → WSGI adapter
# from a2wsgi import ASGIMiddleware

# from main import app as asgi_app

# # Wrap FastAPI ASGI app in WSGI middleware
# application = ASGIMiddleware(asgi_app)


# # 4
# import sys
# import os

# INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
# if sys.executable != INTERP:
#     os.execl(INTERP, INTERP, *sys.argv)

# # This only works if Passenger is configured for ASGI/generic mode
# # Most shared cPanel hosts do NOT support this
# from main import app as application



# v5
import sys
import os
import asyncio

INTERP = "/home/salesne2/virtualenv/intellect-api.salesnet.ng/3.13/bin/python"
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from main import app as fastapi_app

class WSGIAdapter:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    def __call__(self, environ, start_response):
        # Convert WSGI environ to ASGI scope
        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': '1.1',
            'method': environ.get('REQUEST_METHOD', 'GET'),
            'scheme': environ.get('wsgi.url_scheme', 'http'),
            'server': (environ.get('SERVER_NAME', 'localhost'), int(environ.get('SERVER_PORT', 80))),
            'client': (environ.get('REMOTE_ADDR', '127.0.0.1'), 0),
            'root_path': '',
            'path': environ.get('PATH_INFO', '/'),
            'query_string': environ.get('QUERY_STRING', '').encode(),
            'headers': [(k.encode().replace(b'_', b'-'), v.encode()) 
                       for k, v in environ.items() if k.startswith('HTTP_') or k in ('CONTENT_TYPE', 'CONTENT_LENGTH')],
        }

        # Body handling
        body = b''
        if environ.get('REQUEST_METHOD') in ('POST', 'PUT', 'PATCH'):
            content_length = int(environ.get('CONTENT_LENGTH', 0))
            if content_length > 0:
                body = environ['wsgi.input'].read(content_length)

        # ASGI receive/send
        messages = [{'type': 'http.request', 'body': body, 'more_body': False}]
        response_started = False
        response_body = []

        async def receive():
            if messages:
                return messages.pop(0)
            return {'type': 'http.disconnect'}

        async def send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = [(k.decode(), v.decode()) for k, v in message.get('headers', [])]
                start_response(f'{status} OK', headers)
                response_started = True
            elif message['type'] == 'http.response.body':
                chunk = message.get('body', b'')
                if chunk:
                    response_body.append(chunk)

        # Run ASGI app in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.asgi_app(scope, receive, send))
        finally:
            loop.close()

        return response_body

application = WSGIAdapter(fastapi_app)

