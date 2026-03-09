"""
Meetup API Integration for Greenlake Running Group
===================================================

Setup Instructions:
1. Go to https://www.meetup.com/api/oauth/list/
2. Create an OAuth consumer (or use API key if available)
3. For read-only public group data, you may not need authentication

Note: Meetup moved to GraphQL API. Public group events can often be 
fetched without authentication.

Environment Variables (optional for public data):
- MEETUP_API_KEY: Your Meetup API key (if using authenticated endpoints)
"""

import os
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Greenlake Running Group URL name
GREENLAKE_GROUP_URLNAME = "seattle-greenlake-running-group"


@dataclass
class MeetupEvent:
    """Represents a Meetup event."""
    event_id: str
    name: str
    start_time: datetime
    venue_name: str
    venue_address: str
    description: str
    rsvp_count: int
    event_url: str
    
    def to_dict(self) -> dict:
        return {
            "studio": "greenlake",
            "event_id": self.event_id,
            "name": self.name,
            "time": self.start_time.strftime("%H:%M"),
            "date": self.start_time.strftime("%Y-%m-%d"),
            "day_name": self.start_time.strftime("%A"),
            "venue": self.venue_name,
            "address": self.venue_address,
            "rsvp_count": self.rsvp_count,
            "url": self.event_url
        }


class MeetupClient:
    """
    Client for Meetup API (GraphQL).
    
    Documentation: https://www.meetup.com/api/schema/
    """
    
    GRAPHQL_URL = "https://api.meetup.com/gql"
    
    # Fallback: REST API for public events (may still work)
    REST_URL = "https://api.meetup.com"
    
    def __init__(self, group_urlname: str = GREENLAKE_GROUP_URLNAME):
        """
        Initialize the Meetup client.
        
        Args:
            group_urlname: The URL name of the group (from meetup.com/GROUP_NAME/)
        """
        self.group_urlname = group_urlname
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def get_upcoming_events(self, limit: int = 20) -> List[MeetupEvent]:
        """
        Get upcoming events for the group.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of MeetupEvent objects
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        # Try GraphQL first
        events = await self._fetch_graphql(limit)
        
        # Fallback to REST if GraphQL fails
        if not events:
            events = await self._fetch_rest(limit)
        
        return events
    
    async def _fetch_graphql(self, limit: int) -> List[MeetupEvent]:
        """Fetch events using GraphQL API."""
        query = """
        query($urlname: String!, $first: Int) {
            groupByUrlname(urlname: $urlname) {
                name
                upcomingEvents(input: {first: $first}) {
                    edges {
                        node {
                            id
                            title
                            dateTime
                            venue {
                                name
                                address
                                city
                                state
                            }
                            description
                            going
                            eventUrl
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "urlname": self.group_urlname,
            "first": limit
        }
        
        try:
            async with self.session.post(
                self.GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if "errors" in data:
                        logger.warning(f"GraphQL errors: {data['errors']}")
                        return []
                    
                    group_data = data.get("data", {}).get("groupByUrlname", {})
                    edges = group_data.get("upcomingEvents", {}).get("edges", [])
                    
                    return self._parse_graphql_events(edges)
                else:
                    logger.warning(f"GraphQL request failed: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"GraphQL fetch error: {e}")
            return []
    
    async def _fetch_rest(self, limit: int) -> List[MeetupEvent]:
        """Fallback: Fetch events using REST API."""
        try:
            url = f"{self.REST_URL}/{self.group_urlname}/events"
            params = {
                "status": "upcoming",
                "page": limit
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_rest_events(data)
                else:
                    logger.warning(f"REST request failed: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"REST fetch error: {e}")
            return []
    
    def _parse_graphql_events(self, edges: List[dict]) -> List[MeetupEvent]:
        """Parse GraphQL response into MeetupEvent objects."""
        events = []
        for edge in edges:
            node = edge.get("node", {})
            try:
                venue = node.get("venue", {}) or {}
                
                events.append(MeetupEvent(
                    event_id=node.get("id", ""),
                    name=node.get("title", ""),
                    start_time=datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00")),
                    venue_name=venue.get("name", "Green Lake"),
                    venue_address=f"{venue.get('address', '')}, {venue.get('city', 'Seattle')}, {venue.get('state', 'WA')}",
                    description=node.get("description", "")[:200],  # Truncate
                    rsvp_count=node.get("going", 0),
                    event_url=node.get("eventUrl", "")
                ))
            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue
        return events
    
    def _parse_rest_events(self, events_data: List[dict]) -> List[MeetupEvent]:
        """Parse REST API response into MeetupEvent objects."""
        events = []
        for event in events_data:
            try:
                venue = event.get("venue", {}) or {}
                
                # REST API returns time in milliseconds
                start_ms = event.get("time", 0)
                start_time = datetime.fromtimestamp(start_ms / 1000)
                
                events.append(MeetupEvent(
                    event_id=event.get("id", ""),
                    name=event.get("name", ""),
                    start_time=start_time,
                    venue_name=venue.get("name", "Green Lake"),
                    venue_address=f"{venue.get('address_1', '')}, {venue.get('city', 'Seattle')}",
                    description=event.get("description", "")[:200],
                    rsvp_count=event.get("yes_rsvp_count", 0),
                    event_url=event.get("link", f"https://www.meetup.com/{self.group_urlname}/")
                ))
            except Exception as e:
                logger.warning(f"Error parsing REST event: {e}")
                continue
        return events
    
    async def get_events_for_day(self, target_date: datetime) -> List[MeetupEvent]:
        """Get events for a specific day."""
        all_events = await self.get_upcoming_events(limit=30)
        
        target_day = target_date.date()
        return [
            event for event in all_events
            if event.start_time.date() == target_day
        ]
    
    async def get_saturday_runs(self, weeks_ahead: int = 4) -> List[MeetupEvent]:
        """Get Saturday morning runs for the next few weeks."""
        all_events = await self.get_upcoming_events(limit=50)
        
        saturday_runs = []
        for event in all_events:
            # Saturday = weekday 5
            if event.start_time.weekday() == 5:
                # Morning runs (before noon)
                if event.start_time.hour < 12:
                    saturday_runs.append(event)
        
        return saturday_runs[:weeks_ahead]


# Known recurring events (fallback when API fails)
KNOWN_WEEKLY_EVENTS = [
    {
        "name": "Monday Morning On Track",
        "day": 0,  # Monday
        "time": "05:30",
        "venue": "Roosevelt High School Track",
        "description": "Early morning track workout"
    },
    {
        "name": "Monday Evening Track (MET)",
        "day": 0,
        "time": "18:30",
        "venue": "Lower Woodland Park Track",
        "description": "Speed work and intervals, milkshakes at Kidd Valley after"
    },
    {
        "name": "Tuesday Evening Run (TER)",
        "day": 1,
        "time": "18:30",
        "venue": "Green Lake Park Wading Pool",
        "description": "3, 5, or 7 mile routes, pizza at Zeeks after"
    },
    {
        "name": "Wake Up Wednesday (WUW)",
        "day": 2,
        "time": "05:30",
        "venue": "Starbucks - Greenlake",
        "description": "Casual run around the lake"
    },
    {
        "name": "Wednesday Night Run",
        "day": 2,
        "time": "17:30",
        "venue": "Brooks Trailhead, 3400 Stone Way N",
        "description": "4-mile scenic routes, beer at Fremont Brewing after"
    },
    {
        "name": "Saturday Morning Rise & Shine",
        "day": 5,
        "time": "07:00",
        "venue": "Green Lake",
        "description": "Early Saturday group run"
    },
    {
        "name": "Saturday Mid-Morning Run",
        "day": 5,
        "time": "09:00",
        "venue": "Green Lake",
        "description": "Group run around Green Lake"
    },
]


def get_fallback_events(target_date: datetime) -> List[dict]:
    """Get known recurring events for a date (when API fails)."""
    target_weekday = target_date.weekday()
    
    events = []
    for event in KNOWN_WEEKLY_EVENTS:
        if event["day"] == target_weekday:
            events.append({
                "studio": "greenlake",
                "name": event["name"],
                "time": event["time"],
                "date": target_date.strftime("%Y-%m-%d"),
                "venue": event["venue"],
                "description": event["description"],
                "url": f"https://www.meetup.com/{GREENLAKE_GROUP_URLNAME}/"
            })
    
    return events


# Factory function
def create_meetup_client() -> MeetupClient:
    """Create a Meetup client for Greenlake Running Group."""
    return MeetupClient(GREENLAKE_GROUP_URLNAME)


# Test function
async def test_meetup():
    """Test the Meetup integration."""
    async with MeetupClient() as client:
        print("Fetching Greenlake Running Group events...\n")
        
        events = await client.get_upcoming_events(limit=10)
        
        if events:
            print(f"Found {len(events)} upcoming events:\n")
            for event in events:
                print(f"  {event.start_time.strftime('%a %m/%d %I:%M %p')} - {event.name}")
                print(f"    📍 {event.venue_name}")
                print(f"    👥 {event.rsvp_count} going")
                print()
        else:
            print("No events found via API, using fallback schedule:")
            from datetime import date
            today = datetime.now()
            for i in range(7):
                day = today + timedelta(days=i)
                fallback = get_fallback_events(day)
                for event in fallback:
                    print(f"  {event['date']} {event['time']} - {event['name']}")
                    print(f"    📍 {event['venue']}")


if __name__ == "__main__":
    asyncio.run(test_meetup())
