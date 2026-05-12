import secrets
import string
from datetime import datetime, timezone
from fastapi import Request

def generate_secure_code(length: int = 6) -> str:
    """Generate secure verification code (alphanumeric uppercase)"""
    characters = string.ascii_uppercase + string.digits
    # Remove ambiguous characters
    characters = characters.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    return ''.join(secrets.choice(characters) for _ in range(length))


def get_client_ip(request: Request) -> str:
    """Get client IP address with proxy support"""
    # Check X-Forwarded-For header first (for proxies/load balancers)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain
        return forwarded.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct client host
    return request.client.host if request.client else "unknown"
