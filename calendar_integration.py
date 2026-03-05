"""
Google Calendar Integration
============================
Integrates with Google Calendar to check availability and optionally
create workout events.

Setup:
1. Create a Google Cloud project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials
4. Download credentials.json
5. Set GOOGLE_CALENDAR_CREDENTIALS_FILE in .env
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import pytz

# Google Calendar API imports
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    print("Google Calendar API not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

SEATTLE_TZ = pytz.timezone('America/Los_Angeles')

# Scopes required for calendar access
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]


class GoogleCalendarClient:
    """
    Client for interacting with Google Calendar.
    
    For a Slack app with multiple users, you'd want to implement OAuth
    flow per-user and store tokens securely. This is a simplified
    single-user implementation.
    """
    
    def __init__(self, credentials_file: str = "credentials.json", token_file: str = "token.json"):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.creds = None
    
    def authenticate(self) -> bool:
        """
        Authenticate with Google Calendar API.
        
        Returns True if authentication successful.
        """
        if not GOOGLE_AVAILABLE:
            print("Google API libraries not available")
            return False
        
        if not os.path.exists(self.credentials_file):
            print(f"Credentials file not found: {self.credentials_file}")
            return False
        
        # Check for existing token
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        
        # Refresh or create new credentials
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                self.creds = flow.run_local_server(port=0)
            
            # Save the credentials
            with open(self.token_file, 'w') as token:
                token.write(self.creds.to_json())
        
        try:
            self.service = build('calendar', 'v3', credentials=self.creds)
            return True
        except HttpError as error:
            print(f"Error building calendar service: {error}")
            return False
    
    def get_busy_times(self, date: datetime) -> List[Dict]:
        """
        Get busy times for a specific date.
        
        Returns list of busy periods with start/end times.
        """
        if not self.service:
            if not self.authenticate():
                return []
        
        # Set time bounds for the day
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        try:
            # Get events from primary calendar
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_of_day.isoformat() + 'Z',
                timeMax=end_of_day.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            busy_times = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                # Handle all-day events
                if 'date' in event['start']:
                    busy_times.append({
                        'all_day': True,
                        'summary': event.get('summary', 'Busy'),
                        'start': start,
                        'end': end
                    })
                else:
                    busy_times.append({
                        'all_day': False,
                        'summary': event.get('summary', 'Busy'),
                        'start': datetime.fromisoformat(start.replace('Z', '+00:00')),
                        'end': datetime.fromisoformat(end.replace('Z', '+00:00'))
                    })
            
            return busy_times
            
        except HttpError as error:
            print(f"Error fetching calendar: {error}")
            return []
    
    def get_free_slots(self, date: datetime, min_duration: int = 60) -> List[Dict]:
        """
        Find free time slots on a given date.
        
        Args:
            date: Date to check
            min_duration: Minimum slot duration in minutes
        
        Returns:
            List of free slots with start/end times
        """
        busy_times = self.get_busy_times(date)
        
        # Define typical workout hours (5 AM - 9 PM)
        day_start = date.replace(hour=5, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=21, minute=0, second=0, microsecond=0)
        
        if not busy_times:
            return [{
                'start': day_start,
                'end': day_end,
                'duration_minutes': int((day_end - day_start).total_seconds() / 60)
            }]
        
        # Check for all-day events
        for event in busy_times:
            if event.get('all_day'):
                return []  # No free slots on all-day event days
        
        # Sort busy times
        busy_sorted = sorted(
            [b for b in busy_times if not b.get('all_day')],
            key=lambda x: x['start']
        )
        
        free_slots = []
        current_time = day_start
        
        for busy in busy_sorted:
            if busy['start'] > current_time:
                duration = int((busy['start'] - current_time).total_seconds() / 60)
                if duration >= min_duration:
                    free_slots.append({
                        'start': current_time,
                        'end': busy['start'],
                        'duration_minutes': duration
                    })
            current_time = max(current_time, busy['end'])
        
        # Check time after last event
        if current_time < day_end:
            duration = int((day_end - current_time).total_seconds() / 60)
            if duration >= min_duration:
                free_slots.append({
                    'start': current_time,
                    'end': day_end,
                    'duration_minutes': duration
                })
        
        return free_slots
    
    def create_workout_event(
        self,
        title: str,
        start_time: datetime,
        duration_minutes: int = 60,
        location: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Create a workout event on the calendar.
        
        Returns the created event or None on failure.
        """
        if not self.service:
            if not self.authenticate():
                return None
        
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        event = {
            'summary': title,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'America/Los_Angeles',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/Los_Angeles',
            },
        }
        
        if location:
            event['location'] = location
        if description:
            event['description'] = description
        
        # Add color (workout = green)
        event['colorId'] = '10'  # Green
        
        try:
            created_event = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            return created_event
        except HttpError as error:
            print(f"Error creating event: {error}")
            return None
    
    def get_week_availability(self, start_date: Optional[datetime] = None) -> Dict:
        """
        Get availability for the entire week.
        
        Returns dict with date keys and free slot lists.
        """
        if start_date is None:
            start_date = datetime.now(SEATTLE_TZ)
        
        # Find Monday of the week
        monday = start_date - timedelta(days=start_date.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        
        availability = {}
        
        for i in range(7):
            date = monday + timedelta(days=i)
            day_key = date.strftime("%Y-%m-%d")
            availability[day_key] = {
                'date': date,
                'day_name': date.strftime("%A"),
                'busy': self.get_busy_times(date),
                'free_slots': self.get_free_slots(date)
            }
        
        return availability
    
    def format_availability(self, availability: Dict) -> str:
        """Format availability as Slack message."""
        lines = ["📅 *Your Week's Availability*\n"]
        
        for day_key, day_info in sorted(availability.items()):
            day_name = day_info['day_name']
            free_slots = day_info['free_slots']
            
            if not free_slots:
                lines.append(f"*{day_name}*: ❌ Busy all day")
            else:
                slot_strs = []
                for slot in free_slots[:3]:  # Show max 3 slots
                    start = slot['start'].strftime("%I:%M %p")
                    end = slot['end'].strftime("%I:%M %p")
                    slot_strs.append(f"{start}-{end}")
                
                lines.append(f"*{day_name}*: ✅ Free: {', '.join(slot_strs)}")
        
        return "\n".join(lines)


class MockCalendarClient:
    """
    Mock calendar client for testing without Google integration.
    
    Simulates a typical work schedule.
    """
    
    def __init__(self):
        self.mock_events = self._generate_mock_events()
    
    def _generate_mock_events(self) -> Dict:
        """Generate mock work schedule."""
        today = datetime.now(SEATTLE_TZ)
        monday = today - timedelta(days=today.weekday())
        
        events = {}
        
        for i in range(5):  # Weekdays only
            date = monday + timedelta(days=i)
            day_key = date.strftime("%Y-%m-%d")
            
            # Typical work hours with some meetings
            events[day_key] = [
                {
                    'summary': 'Work Block',
                    'start': date.replace(hour=9, minute=0),
                    'end': date.replace(hour=12, minute=0),
                    'all_day': False
                },
                {
                    'summary': 'Lunch',
                    'start': date.replace(hour=12, minute=0),
                    'end': date.replace(hour=13, minute=0),
                    'all_day': False
                },
                {
                    'summary': 'Work Block',
                    'start': date.replace(hour=13, minute=0),
                    'end': date.replace(hour=17, minute=0),
                    'all_day': False
                },
            ]
            
            # Add some random meetings
            if i == 1:  # Tuesday
                events[day_key].append({
                    'summary': 'Team Meeting',
                    'start': date.replace(hour=17, minute=30),
                    'end': date.replace(hour=18, minute=30),
                    'all_day': False
                })
        
        return events
    
    def get_busy_times(self, date: datetime) -> List[Dict]:
        """Get mock busy times."""
        day_key = date.strftime("%Y-%m-%d")
        return self.mock_events.get(day_key, [])
    
    def get_free_slots(self, date: datetime, min_duration: int = 60) -> List[Dict]:
        """Find free time slots in mock calendar."""
        busy_times = self.get_busy_times(date)
        
        day_start = date.replace(hour=5, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=21, minute=0, second=0, microsecond=0)
        
        if not busy_times:
            return [{
                'start': day_start,
                'end': day_end,
                'duration_minutes': int((day_end - day_start).total_seconds() / 60)
            }]
        
        busy_sorted = sorted(busy_times, key=lambda x: x['start'])
        
        free_slots = []
        current_time = day_start
        
        for busy in busy_sorted:
            if busy['start'] > current_time:
                duration = int((busy['start'] - current_time).total_seconds() / 60)
                if duration >= min_duration:
                    free_slots.append({
                        'start': current_time,
                        'end': busy['start'],
                        'duration_minutes': duration
                    })
            current_time = max(current_time, busy['end'])
        
        if current_time < day_end:
            duration = int((day_end - current_time).total_seconds() / 60)
            if duration >= min_duration:
                free_slots.append({
                    'start': current_time,
                    'end': day_end,
                    'duration_minutes': duration
                })
        
        return free_slots
    
    def get_week_availability(self, start_date: Optional[datetime] = None) -> Dict:
        """Get mock week availability."""
        if start_date is None:
            start_date = datetime.now(SEATTLE_TZ)
        
        monday = start_date - timedelta(days=start_date.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        
        availability = {}
        
        for i in range(7):
            date = monday + timedelta(days=i)
            day_key = date.strftime("%Y-%m-%d")
            availability[day_key] = {
                'date': date,
                'day_name': date.strftime("%A"),
                'busy': self.get_busy_times(date),
                'free_slots': self.get_free_slots(date)
            }
        
        return availability
    
    def format_availability(self, availability: Dict) -> str:
        """Format availability as Slack message."""
        lines = ["📅 *Your Week's Availability* _(mock data)_\n"]
        
        for day_key, day_info in sorted(availability.items()):
            day_name = day_info['day_name']
            free_slots = day_info['free_slots']
            
            if not free_slots:
                lines.append(f"*{day_name}*: ❌ Busy all day")
            else:
                slot_strs = []
                for slot in free_slots[:3]:
                    start = slot['start'].strftime("%I:%M %p")
                    end = slot['end'].strftime("%I:%M %p")
                    slot_strs.append(f"{start}-{end}")
                
                lines.append(f"*{day_name}*: ✅ Free: {', '.join(slot_strs)}")
        
        return "\n".join(lines)


def get_calendar_client() -> object:
    """
    Factory function to get the appropriate calendar client.
    
    Returns GoogleCalendarClient if configured, else MockCalendarClient.
    """
    credentials_file = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_FILE")
    
    if credentials_file and os.path.exists(credentials_file) and GOOGLE_AVAILABLE:
        client = GoogleCalendarClient(credentials_file)
        if client.authenticate():
            return client
    
    return MockCalendarClient()


# Test the module
if __name__ == "__main__":
    print("Testing calendar integration...\n")
    
    client = get_calendar_client()
    
    today = datetime.now(SEATTLE_TZ)
    print(f"Checking availability for week of {today.strftime('%B %d, %Y')}...\n")
    
    availability = client.get_week_availability(today)
    print(client.format_availability(availability))
