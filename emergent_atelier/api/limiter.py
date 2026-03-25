"""Shared SlowAPI rate limiter instance.

Defined here (not in server.py) so that routers like marketplace.py
can import it without creating a circular dependency.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
