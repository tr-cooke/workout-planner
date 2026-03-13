"""
Greenlake Running Group Schedule
=================================

Hardcoded weekly schedule from Meetup.
https://www.meetup.com/seattle-greenlake-running-group/events/

This is a consistent weekly schedule that rarely changes.
"""

from datetime import datetime, timedelta
from typing import List, Dict
import pytz

SEATTLE_TZ = pytz.timezone("America/Los_Angeles")

# Weekly Greenlake Running Group schedule
# Format: (time_24h, event_name, location, notes)
GREENLAKE_SCHEDULE = {
    0: [  # Monday
        ("05:30", "Monday Morning Track", "Track", "Early morning track workout"),
        ("18:30", "Monday Evening Track", "Track", "Evening track workout"),
    ],
    1: [  # Tuesday
        ("18:30", "Tuesday Evening Run", "Green Lake", "Evening group run"),
    ],
    2: [  # Wednesday
        ("05:30", "Wake Up Wednesday", "Green Lake", "Early morning run"),
        ("17:30", "Wednesday Night Trailhead Run", "Trailhead", "Trail run"),
    ],
    3: [  # Thursday
        ("18:30", "Thursday Evening Casual Run", "Green Lake", "Casual evening run"),
    ],
    4: [  # Friday
        ("06:00", "Friday Lake Union Run", "Lake Union", "Morning run around Lake Union"),
    ],
    5: [  # Saturday
        ("07:00", "Saturday Rise and Shine", "Green Lake", "Early Saturday run"),
        ("09:00", "Saturday Mid-Morning", "Green Lake", "Mid-morning Saturday run"),
    ],
    6: [  # Sunday
        # No regular Sunday runs
    ],
}


def get_greenlake_schedule_for_date(target_date: datetime) -> List[Dict]:
    """Get Greenlake Running Group events for a specific date."""
    weekday = target_date.weekday()
    date_str = target_date.strftime("%Y-%m-%d")
    
    events = []
    for time, name, location, notes in GREENLAKE_SCHEDULE.get(weekday, []):
        events.append({
            "studio": "greenlake",
            "class_name": name,
            "name": name,
            "time": time,
            "date": date_str,
            "location": location,
            "notes": notes,
            "duration_minutes": 60,
            "instructor": ""
        })
    
    return events


def get_greenlake_schedule_for_week(start_date: datetime = None) -> List[Dict]:
    """Get Greenlake Running Group events for a week."""
    if start_date is None:
        start_date = datetime.now(SEATTLE_TZ)
    
    all_events = []
    for i in range(7):
        date = start_date + timedelta(days=i)
        all_events.extend(get_greenlake_schedule_for_date(date))
    
    return all_events


def get_greenlake_schedule_for_days(days_ahead: int = 14) -> List[Dict]:
    """Get Greenlake Running Group events for the next N days."""
    today = datetime.now(SEATTLE_TZ)
    
    all_events = []
    for i in range(days_ahead):
        date = today + timedelta(days=i)
        all_events.extend(get_greenlake_schedule_for_date(date))
    
    return all_events


# Test function
def test_schedule():
    """Test the Greenlake schedule."""
    print("Greenlake Running Group Schedule")
    print("=" * 50)
    
    today = datetime.now(SEATTLE_TZ)
    
    for i in range(7):
        date = today + timedelta(days=i)
        events = get_greenlake_schedule_for_date(date)
        
        day_name = date.strftime("%A %m/%d")
        print(f"\n{day_name}:")
        
        if events:
            for event in events:
                print(f"  {event['time']} - {event['name']} @ {event['location']}")
        else:
            print("  No runs scheduled")


if __name__ == "__main__":
    test_schedule()