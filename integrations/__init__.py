"""
Integrations Module
===================

This module contains API clients and scrapers for fetching fitness schedules.

Available integrations:
- Mindbody API (barre3)
- Meetup API (Greenlake Running Group)
- Browser scrapers (solidcore, Cycle Sanctuary, Ballard Pool)
"""

# Import what we can, gracefully handle missing dependencies
try:
    from .mindbody_client import MindbodyClient, create_barre3_client
except ImportError:
    MindbodyClient = None
    create_barre3_client = None

try:
    from .meetup_client import MeetupClient, create_meetup_client, get_fallback_events
except ImportError:
    MeetupClient = None
    create_meetup_client = None
    get_fallback_events = None

# Skip browser_scrapers - it has issues with Playwright types
# Use solidcore_scraper directly instead
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

__all__ = [
    'MindbodyClient',
    'create_barre3_client',
    'MeetupClient', 
    'create_meetup_client',
    'get_fallback_events',
    'PLAYWRIGHT_AVAILABLE',
]