"""
Schedule Scraper Module
========================
Fetches class schedules from various fitness studio websites.

Note: Many fitness studios use JavaScript-heavy booking widgets that require
browser automation (Selenium/Playwright) to scrape. This module provides
structure for both API-based and scraping-based approaches.
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json
import re
from bs4 import BeautifulSoup
import pytz

SEATTLE_TZ = pytz.timezone('America/Los_Angeles')


class ScheduleFetcher:
    """Base class for schedule fetching."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def fetch_schedule(self, date: datetime) -> List[Dict]:
        """Override in subclass."""
        raise NotImplementedError


class CycleSanctuarySchedule(ScheduleFetcher):
    """
    Fetch Cycle Sanctuary schedule.
    
    Uses Mariana Tek API (their booking platform).
    """
    
    BASE_URL = "https://www.thecyclesanctuary.com"
    
    async def fetch_schedule(self, date: datetime) -> List[Dict]:
        """
        Note: Cycle Sanctuary uses Mariana Tek, which requires API access
        or browser automation to fetch the actual schedule.
        
        For production, you would either:
        1. Use their official API if available
        2. Use Playwright/Selenium to render the JavaScript
        3. Use their mobile app's API endpoints
        
        For now, return typical class times based on their known schedule.
        """
        classes = []
        day_of_week = date.weekday()
        
        # Based on Yelp listing and typical schedule patterns
        typical_schedule = {
            0: [  # Monday
                {"time": "17:00", "class": "Power Cycle 45", "duration": 45},
                {"time": "18:00", "class": "HIIT Cycle", "duration": 45},
            ],
            1: [  # Tuesday
                {"time": "06:00", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:00", "class": "Performance Cycle 60", "duration": 60},
                {"time": "17:30", "class": "Power Cycle 45", "duration": 45},
                {"time": "18:30", "class": "HIIT Cycle", "duration": 45},
            ],
            2: [  # Wednesday
                {"time": "06:00", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:00", "class": "Performance Cycle 60", "duration": 60},
                {"time": "17:30", "class": "Power Cycle 45", "duration": 45},
                {"time": "18:30", "class": "Strength/HIIT Cycle", "duration": 45},
            ],
            3: [  # Thursday
                {"time": "06:00", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:00", "class": "Performance Cycle 60", "duration": 60},
                {"time": "17:30", "class": "Power Cycle 45", "duration": 45},
                {"time": "18:30", "class": "HIIT Cycle", "duration": 45},
            ],
            4: [  # Friday
                {"time": "06:00", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:00", "class": "Performance Cycle 60", "duration": 60},
            ],
            5: [  # Saturday
                {"time": "08:30", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:30", "class": "Performance Cycle 60", "duration": 60},
                {"time": "10:45", "class": "Pilates", "duration": 50},
            ],
            6: [  # Sunday
                {"time": "08:30", "class": "Power Cycle 45", "duration": 45},
                {"time": "09:30", "class": "Performance Cycle 60", "duration": 60},
                {"time": "10:45", "class": "Core & Stretch", "duration": 45},
            ],
        }
        
        day_classes = typical_schedule.get(day_of_week, [])
        
        for cls in day_classes:
            classes.append({
                "studio": "cycle",
                "name": cls["class"],
                "time": cls["time"],
                "duration_minutes": cls["duration"],
                "date": date.strftime("%Y-%m-%d"),
                "bookable": self._is_bookable(date),
                "url": "https://www.thecyclesanctuary.com/schedule"
            })
        
        return classes
    
    def _is_bookable(self, date: datetime) -> bool:
        """Check if date is within booking window (1 week out)."""
        today = datetime.now(SEATTLE_TZ).date()
        target = date.date() if hasattr(date, 'date') else date
        days_out = (target - today).days
        return 0 <= days_out <= 7


class SolidcoreSchedule(ScheduleFetcher):
    """
    Fetch solidcore schedule.
    
    solidcore uses their own booking system at solidcore.co/auth/schedule
    """
    
    async def fetch_schedule(self, date: datetime) -> List[Dict]:
        """
        solidcore schedule. Their website requires authentication to view.
        
        Typical class times based on common patterns:
        """
        classes = []
        day_of_week = date.weekday()
        
        # solidcore typically offers classes from early morning to evening
        typical_schedule = {
            0: [  # Monday
                {"time": "06:00", "class": "[solidcore]", "duration": 50},
                {"time": "07:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "12:00", "class": "[solidcore]", "duration": 50},
                {"time": "17:30", "class": "[solidcore]", "duration": 50},
                {"time": "18:30", "class": "[solidcore]", "duration": 50},
                {"time": "19:30", "class": "[solidcore]", "duration": 50},
            ],
            1: [  # Tuesday
                {"time": "06:00", "class": "[solidcore]", "duration": 50},
                {"time": "07:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "12:00", "class": "[solidcore]", "duration": 50},
                {"time": "17:30", "class": "[solidcore]", "duration": 50},
                {"time": "18:30", "class": "[solidcore]", "duration": 50},
            ],
            2: [  # Wednesday
                {"time": "06:00", "class": "[solidcore]", "duration": 50},
                {"time": "07:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "12:00", "class": "[solidcore]", "duration": 50},
                {"time": "17:30", "class": "[solidcore]", "duration": 50},
                {"time": "18:30", "class": "[solidcore]", "duration": 50},
            ],
            3: [  # Thursday
                {"time": "06:00", "class": "[solidcore]", "duration": 50},
                {"time": "07:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "12:00", "class": "[solidcore]", "duration": 50},
                {"time": "17:30", "class": "[solidcore]", "duration": 50},
                {"time": "18:30", "class": "[solidcore]", "duration": 50},
            ],
            4: [  # Friday
                {"time": "06:00", "class": "[solidcore]", "duration": 50},
                {"time": "07:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "12:00", "class": "[solidcore]", "duration": 50},
                {"time": "17:00", "class": "[solidcore]", "duration": 50},
            ],
            5: [  # Saturday
                {"time": "08:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "10:00", "class": "[solidcore]", "duration": 50},
                {"time": "11:00", "class": "[solidcore]", "duration": 50},
            ],
            6: [  # Sunday
                {"time": "08:00", "class": "[solidcore]", "duration": 50},
                {"time": "09:00", "class": "[solidcore]", "duration": 50},
                {"time": "10:00", "class": "[solidcore]", "duration": 50},
                {"time": "11:00", "class": "[solidcore]", "duration": 50},
            ],
        }
        
        day_classes = typical_schedule.get(day_of_week, [])
        
        for cls in day_classes:
            classes.append({
                "studio": "solidcore",
                "name": cls["class"],
                "time": cls["time"],
                "duration_minutes": cls["duration"],
                "date": date.strftime("%Y-%m-%d"),
                "bookable": self._is_bookable(date),
                "url": "https://solidcore.co/auth/schedule"
            })
        
        return classes
    
    def _is_bookable(self, date: datetime) -> bool:
        """
        solidcore opens booking on the 1st of each month.
        Check if the date's month has opened for booking.
        """
        today = datetime.now(SEATTLE_TZ)
        target = date if hasattr(date, 'month') else datetime.strptime(str(date), "%Y-%m-%d")
        
        # If we're in the same month or a past month, it's bookable
        if target.year < today.year:
            return True
        if target.year == today.year and target.month <= today.month:
            return True
        # If it's next month and we're past the 1st, it should be open
        if target.year == today.year and target.month == today.month + 1 and today.day >= 1:
            return True
        
        return False


class Barre3Schedule(ScheduleFetcher):
    """
    Fetch barre3 Ballard schedule.
    
    barre3 uses their own booking widget that requires JavaScript.
    """
    
    async def fetch_schedule(self, date: datetime) -> List[Dict]:
        """
        barre3 schedule - requires JavaScript widget to render.
        
        Typical class patterns:
        """
        classes = []
        day_of_week = date.weekday()
        
        # barre3 typical schedule
        typical_schedule = {
            0: [  # Monday
                {"time": "06:00", "class": "barre3", "duration": 60},
                {"time": "09:30", "class": "barre3", "duration": 60},
                {"time": "12:00", "class": "barre3 Express", "duration": 40},
                {"time": "17:30", "class": "barre3", "duration": 60},
                {"time": "18:45", "class": "barre3", "duration": 60},
            ],
            1: [  # Tuesday
                {"time": "06:00", "class": "barre3", "duration": 60},
                {"time": "09:30", "class": "barre3", "duration": 60},
                {"time": "12:00", "class": "barre3 Express", "duration": 40},
                {"time": "17:30", "class": "barre3", "duration": 60},
                {"time": "18:45", "class": "barre3", "duration": 60},
            ],
            2: [  # Wednesday
                {"time": "06:00", "class": "barre3", "duration": 60},
                {"time": "09:30", "class": "barre3", "duration": 60},
                {"time": "12:00", "class": "barre3 Express", "duration": 40},
                {"time": "17:30", "class": "barre3", "duration": 60},
                {"time": "18:45", "class": "barre3", "duration": 60},
            ],
            3: [  # Thursday
                {"time": "06:00", "class": "barre3", "duration": 60},
                {"time": "09:30", "class": "barre3", "duration": 60},
                {"time": "12:00", "class": "barre3 Express", "duration": 40},
                {"time": "17:30", "class": "barre3", "duration": 60},
                {"time": "18:45", "class": "barre3", "duration": 60},
            ],
            4: [  # Friday
                {"time": "06:00", "class": "barre3", "duration": 60},
                {"time": "09:30", "class": "barre3", "duration": 60},
                {"time": "12:00", "class": "barre3 Express", "duration": 40},
                {"time": "16:30", "class": "barre3", "duration": 60},
            ],
            5: [  # Saturday
                {"time": "08:00", "class": "barre3", "duration": 60},
                {"time": "09:15", "class": "barre3", "duration": 60},
                {"time": "10:30", "class": "barre3", "duration": 60},
            ],
            6: [  # Sunday
                {"time": "08:30", "class": "barre3", "duration": 60},
                {"time": "09:45", "class": "barre3", "duration": 60},
                {"time": "11:00", "class": "barre3", "duration": 60},
            ],
        }
        
        day_classes = typical_schedule.get(day_of_week, [])
        
        for cls in day_classes:
            classes.append({
                "studio": "barre3",
                "name": cls["class"],
                "time": cls["time"],
                "duration_minutes": cls["duration"],
                "date": date.strftime("%Y-%m-%d"),
                "bookable": self._is_bookable(date),
                "url": "https://barre3.com/studio-locations/ballard/schedule#schedule_class_widget"
            })
        
        return classes
    
    def _is_bookable(self, date: datetime) -> bool:
        """Check if date is within booking window (1 week out)."""
        today = datetime.now(SEATTLE_TZ).date()
        target = date.date() if hasattr(date, 'date') else date
        days_out = (target - today).days
        return 0 <= days_out <= 7


class BallardPoolSchedule(ScheduleFetcher):
    """
    Fetch Ballard Public Pool schedule from Seattle Parks.
    
    Uses ActiveCommunities platform.
    """
    
    BASE_URL = "https://anc.apm.activecommunities.com/seattle/calendars"
    
    async def fetch_schedule(self, date: datetime) -> List[Dict]:
        """
        Seattle Parks uses ActiveCommunities which requires API access
        or browser automation.
        
        Typical lap swim times:
        """
        classes = []
        day_of_week = date.weekday()
        
        # Ballard Pool typical lap swim schedule
        typical_schedule = {
            0: [  # Monday
                {"time": "05:30", "class": "Lap Swim", "duration": 90},
                {"time": "12:00", "class": "Lap Swim", "duration": 60},
                {"time": "18:00", "class": "Lap Swim", "duration": 90},
            ],
            1: [  # Tuesday
                {"time": "05:30", "class": "Lap Swim", "duration": 90},
                {"time": "12:00", "class": "Lap Swim", "duration": 60},
                {"time": "18:00", "class": "Lap Swim", "duration": 90},
            ],
            2: [  # Wednesday
                {"time": "05:30", "class": "Lap Swim", "duration": 90},
                {"time": "12:00", "class": "Lap Swim", "duration": 60},
                {"time": "18:00", "class": "Lap Swim", "duration": 90},
            ],
            3: [  # Thursday
                {"time": "05:30", "class": "Lap Swim", "duration": 90},
                {"time": "12:00", "class": "Lap Swim", "duration": 60},
                {"time": "18:00", "class": "Lap Swim", "duration": 90},
            ],
            4: [  # Friday
                {"time": "05:30", "class": "Lap Swim", "duration": 90},
                {"time": "12:00", "class": "Lap Swim", "duration": 60},
            ],
            5: [  # Saturday
                {"time": "08:00", "class": "Lap Swim", "duration": 120},
            ],
            6: [  # Sunday
                {"time": "08:00", "class": "Lap Swim", "duration": 120},
            ],
        }
        
        day_classes = typical_schedule.get(day_of_week, [])
        
        for cls in day_classes:
            classes.append({
                "studio": "pool",
                "name": cls["class"],
                "time": cls["time"],
                "duration_minutes": cls["duration"],
                "date": date.strftime("%Y-%m-%d"),
                "bookable": True,  # Pool typically allows same-day drop-in
                "url": "https://anc.apm.activecommunities.com/seattle/calendars?onlineSiteId=0&no_scroll_top=true&defaultCalendarId=6&locationId=26&displayType=0&view=2"
            })
        
        return classes


class GreenlakeRunningGroup:
    """
    Fetch Greenlake Running Group events from Meetup.
    
    Note: Meetup API requires authentication. This provides known schedule.
    """
    
    MEETUP_URL = "https://www.meetup.com/seattle-greenlake-running-group/"
    
    def get_weekly_events(self) -> List[Dict]:
        """
        Known weekly recurring events from the Greenlake Running Group.
        Based on their Meetup page.
        """
        return [
            {
                "name": "Monday Morning On Track",
                "day": "Monday",
                "time": "05:30",
                "location": "Roosevelt High School Track",
                "description": "Early morning track workout"
            },
            {
                "name": "Monday Evening Track (MET)",
                "day": "Monday",
                "time": "18:30",
                "location": "Lower Woodland Park Track",
                "description": "Speed work and intervals"
            },
            {
                "name": "Tuesday Evening Run (TER)",
                "day": "Tuesday",
                "time": "18:30",
                "location": "Green Lake Park Wading Pool",
                "description": "3, 5, or 7 mile routes with pizza after"
            },
            {
                "name": "Wake Up Wednesday (WUW)",
                "day": "Wednesday",
                "time": "05:30",
                "location": "Starbucks - Greenlake",
                "description": "Casual run around the lake"
            },
            {
                "name": "Wednesday Night Run",
                "day": "Wednesday",
                "time": "17:30",
                "location": "Brooks Trailhead, 3400 Stone Way N",
                "description": "4-mile scenic routes, beer at Fremont Brewing after"
            },
            {
                "name": "Thursday Evening Casual Run",
                "day": "Thursday",
                "time": "18:30",
                "location": "Green Lake",
                "description": "Casual evening run"
            },
            {
                "name": "Friday Lake Union Run",
                "day": "Friday",
                "time": "06:00",
                "location": "Lake Union",
                "description": "Early morning run"
            },
            {
                "name": "Saturday Morning Rise & Shine",
                "day": "Saturday",
                "time": "07:00",
                "location": "Green Lake",
                "description": "Early Saturday run"
            },
            {
                "name": "Saturday Mid-Morning Run",
                "day": "Saturday",
                "time": "09:00",
                "location": "Green Lake",
                "description": "Group run around Green Lake"
            },
        ]
    
    def get_event_for_day(self, day_name: str) -> List[Dict]:
        """Get events for a specific day."""
        events = self.get_weekly_events()
        return [e for e in events if e["day"].lower() == day_name.lower()]


class WeatherService:
    """
    Fetch Seattle weather from a weather API.
    """
    
    # Seattle coordinates
    LAT = 47.6062
    LON = -122.3321
    
    async def get_forecast(self, api_key: Optional[str] = None) -> Dict:
        """
        Fetch weather forecast.
        
        For production, use OpenWeatherMap, WeatherAPI, or similar.
        """
        if not api_key:
            # Return mock data
            return self._get_mock_forecast()
        
        # Real API call would go here
        async with aiohttp.ClientSession() as session:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={self.LAT}&lon={self.LON}&appid={api_key}&units=imperial"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_openweather(data)
                else:
                    return self._get_mock_forecast()
    
    def _parse_openweather(self, data: Dict) -> Dict:
        """Parse OpenWeatherMap API response."""
        forecast = {
            "current": {},
            "daily": []
        }
        
        if "list" in data and len(data["list"]) > 0:
            current = data["list"][0]
            forecast["current"] = {
                "temp": round(current["main"]["temp"]),
                "description": current["weather"][0]["description"],
                "humidity": current["main"]["humidity"],
                "wind_speed": round(current["wind"]["speed"])
            }
            
            # Group by day
            daily_data = {}
            for item in data["list"]:
                date = item["dt_txt"].split(" ")[0]
                if date not in daily_data:
                    daily_data[date] = {
                        "date": date,
                        "high": item["main"]["temp"],
                        "low": item["main"]["temp"],
                        "description": item["weather"][0]["description"],
                        "rain_chance": item.get("pop", 0) * 100
                    }
                else:
                    daily_data[date]["high"] = max(daily_data[date]["high"], item["main"]["temp"])
                    daily_data[date]["low"] = min(daily_data[date]["low"], item["main"]["temp"])
            
            forecast["daily"] = list(daily_data.values())[:7]
        
        return forecast
    
    def _get_mock_forecast(self) -> Dict:
        """Return mock weather data."""
        today = datetime.now(SEATTLE_TZ)
        
        return {
            "current": {
                "temp": 52,
                "description": "Partly cloudy",
                "humidity": 68,
                "wind_speed": 8
            },
            "daily": [
                {"date": (today + timedelta(days=i)).strftime("%Y-%m-%d"),
                 "high": 52 + i,
                 "low": 42 + i,
                 "description": ["Partly cloudy", "Rainy", "Rainy", "Cloudy", "Sunny", "Partly cloudy", "Cloudy"][i],
                 "rain_chance": [30, 80, 70, 40, 10, 25, 45][i]}
                for i in range(7)
            ]
        }
    
    def format_forecast(self, forecast: Dict) -> str:
        """Format forecast as Slack message."""
        current = forecast["current"]
        daily = forecast["daily"]
        
        weather_emoji = {
            "clear": "☀️",
            "sunny": "☀️",
            "partly": "⛅",
            "cloud": "☁️",
            "rain": "🌧️",
            "thunder": "⛈️",
            "snow": "❄️",
            "fog": "🌫️",
            "mist": "🌫️"
        }
        
        def get_emoji(desc: str) -> str:
            desc_lower = desc.lower()
            for key, emoji in weather_emoji.items():
                if key in desc_lower:
                    return emoji
            return "🌤️"
        
        lines = [
            f"☀️ *Seattle Weather*\n",
            f"🌡️ *Now:* {current['temp']}°F - {current['description'].title()}",
            f"💨 Wind: {current['wind_speed']} mph | 💧 Humidity: {current['humidity']}%\n",
            "*This Week:*"
        ]
        
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
        for i, day in enumerate(daily[:7]):
            date = datetime.strptime(day["date"], "%Y-%m-%d")
            day_name = day_names[date.weekday()]
            emoji = get_emoji(day["description"])
            rain = f"🌧️ {day['rain_chance']:.0f}%" if day['rain_chance'] > 30 else ""
            
            special_note = ""
            if date.weekday() == 5:  # Saturday
                if day['rain_chance'] < 30:
                    special_note = " _(Great for Greenlake run!)_"
                else:
                    special_note = " _(Consider indoor backup)_"
            
            lines.append(f"• *{day_name}:* {day['high']:.0f}°F {emoji} {rain}{special_note}")
        
        lines.append("\n_💡 Tip: Check weather before outdoor runs!_")
        
        return "\n".join(lines)


# Unified schedule fetcher
async def fetch_all_schedules(date: datetime) -> Dict[str, List[Dict]]:
    """Fetch schedules from all studios for a given date."""
    results = {}
    
    fetchers = {
        "cycle": CycleSanctuarySchedule(),
        "solidcore": SolidcoreSchedule(),
        "barre3": Barre3Schedule(),
        "pool": BallardPoolSchedule(),
    }
    
    for name, fetcher in fetchers.items():
        try:
            results[name] = await fetcher.fetch_schedule(date)
        except Exception as e:
            results[name] = []
            print(f"Error fetching {name} schedule: {e}")
    
    # Add running group
    running = GreenlakeRunningGroup()
    day_name = date.strftime("%A")
    results["greenlake"] = [
        {
            "studio": "greenlake",
            "name": e["name"],
            "time": e["time"],
            "date": date.strftime("%Y-%m-%d"),
            "location": e["location"],
            "description": e["description"],
            "url": "https://www.meetup.com/seattle-greenlake-running-group/"
        }
        for e in running.get_event_for_day(day_name)
    ]
    
    return results


# Test the module
if __name__ == "__main__":
    async def test():
        today = datetime.now(SEATTLE_TZ)
        
        print("Fetching schedules for today...")
        schedules = await fetch_all_schedules(today)
        
        for studio, classes in schedules.items():
            print(f"\n{studio.upper()}:")
            for cls in classes[:3]:  # Show first 3
                print(f"  - {cls['time']}: {cls['name']}")
        
        print("\n\nWeather forecast:")
        weather = WeatherService()
        forecast = await weather.get_forecast()
        print(weather.format_forecast(forecast))
    
    asyncio.run(test())
