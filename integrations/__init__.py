"""
Integrations Module
===================

This module contains API clients and scrapers for fetching fitness schedules.

Available integrations:
- Mindbody API (barre3)
- Meetup API (Greenlake Running Group)
- Browser scrapers (solidcore, Cycle Sanctuary, Ballard Pool)
"""

from .mindbody_client import MindbodyClient, create_barre3_client
from .meetup_client import MeetupClient, create_meetup_client, get_fallback_events
from .browser_scrapers import (
    ScheduleAggregator,
    SolidcoreScraper,
    CycleSanctuaryScraper,
    BallardPoolScraper,
    create_schedule_aggregator,
    PLAYWRIGHT_AVAILABLE
)

__all__ = [
    'MindbodyClient',
    'create_barre3_client',
    'MeetupClient', 
    'create_meetup_client',
    'get_fallback_events',
    'ScheduleAggregator',
    'SolidcoreScraper',
    'CycleSanctuaryScraper',
    'BallardPoolScraper',
    'create_schedule_aggregator',
    'PLAYWRIGHT_AVAILABLE',
]
