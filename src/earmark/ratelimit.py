from slowapi import Limiter
from slowapi.util import get_remote_address

# Per-client rate limiter, shared across routers. Uses the in-memory backend,
# which is sufficient for the single-instance deployment earmark targets.
limiter = Limiter(key_func=get_remote_address)
