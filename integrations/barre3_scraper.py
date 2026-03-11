"""
barre3 Ballard Schedule Scraper
================================

Scrapes the public schedule from barre3.com/studio-locations/ballard/schedule
Uses Mariana Tek widget (same as Cycle Sanctuary).

Usage:
    python integrations/barre3_scraper.py
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import pytz

logger = logging.getLogger(__name__)

SEATTLE_TZ = pytz.timezone("America/Los_Angeles")

# Check if Playwright is available
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed.")


@dataclass
class Barre3Class:
    """Represents a barre3 class."""
    name: str  # e.g., "barre3 Signature 45", "barre3 Signature Livestream 45"
    time: str  # e.g., "06:00" (24-hour format)
    date: str  # e.g., "2026-03-10"
    instructor: str
    duration_minutes: int
    room: str  # "Studio 1", "Studio 2", "Livestream"
    location: str  # "Seattle - Ballard"
    
    def to_dict(self) -> dict:
        return {
            "studio": "barre3",
            "class_name": self.name,
            "name": self.name,
            "time": self.time,
            "date": self.date,
            "instructor": self.instructor,
            "duration_minutes": self.duration_minutes,
            "room": self.room,
            "location": self.location
        }


def parse_time_to_24h(time_str: str) -> str:
    """Convert '5:45 AM' or '12:00 PM' to '05:45' or '12:00' (24-hour format)."""
    time_str = time_str.strip().upper()
    try:
        dt = datetime.strptime(time_str, "%I:%M %p")
        return dt.strftime("%H:%M")
    except ValueError:
        try:
            dt = datetime.strptime(time_str, "%I:%M%p")
            return dt.strftime("%H:%M")
        except ValueError:
            return time_str


def parse_duration(duration_str: str) -> int:
    """Parse '45 min.' or '60 min' to integer minutes."""
    match = re.search(r'(\d+)\s*min', duration_str.lower())
    if match:
        return int(match.group(1))
    return 45  # Default for barre3


async def scrape_barre3_schedule(days_ahead: int = 7) -> List[Barre3Class]:
    """
    Scrape barre3 Ballard schedule.
    
    Args:
        days_ahead: Number of days to fetch (default 7)
        
    Returns:
        List of Barre3Class objects
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available")
        return []
    
    all_classes = []
    
    try:
        async with async_playwright() as p:
            # Use Firefox instead of Chromium - better at avoiding detection
            # Also add anti-detection arguments
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )
            page = await context.new_page()
            
            # barre3 Ballard schedule URL
            base_url = "https://barre3.com/studio-locations/ballard/schedule"
            
            for day_offset in range(min(days_ahead, 7)):
                target_date = datetime.now(SEATTLE_TZ) + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")
                day_name = target_date.strftime("%a").upper()
                
                logger.info(f"Loading schedule for {target_date.strftime('%A %m/%d')}...")
                
                if day_offset == 0:
                    await page.goto(base_url, wait_until="networkidle")
                    await page.wait_for_timeout(3000)
                    
                    # Click ALLOW ALL on cookie banner
                    try:
                        allow_btn = await page.query_selector('text=ALLOW ALL')
                        if allow_btn:
                            await allow_btn.click()
                            logger.info("Clicked ALLOW ALL on cookie banner")
                            await page.wait_for_timeout(2000)
                    except:
                        pass
                    
                    # Wait for schedule to load
                    await page.wait_for_timeout(5000)
                else:
                    # Click on day tab
                    try:
                        day_button = await page.query_selector(f'text="{day_name}"')
                        if day_button:
                            await day_button.click()
                            await page.wait_for_timeout(2000)
                    except Exception as e:
                        logger.warning(f"Could not click day button {day_name}: {e}")
                
                # Extract classes
                classes_for_day = await extract_barre3_classes(page, date_str)
                all_classes.extend(classes_for_day)
                
                logger.info(f"  Found {len(classes_for_day)} classes")
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping barre3: {e}")
        import traceback
        traceback.print_exc()
    
    return all_classes


async def extract_barre3_classes(page, date_str: str) -> List[Barre3Class]:
    """Extract class information from the current page state."""
    classes = []
    
    try:
        # The schedule is in a Mariana Tek iframe - find it
        all_text = ""
        
        # First try to find the iframe
        iframes = await page.query_selector_all('iframe')
        for iframe in iframes:
            try:
                frame = await iframe.content_frame()
                if frame:
                    frame_text = await frame.inner_text('body')
                    # Check if this iframe has schedule content
                    if any(x in frame_text for x in ['AM', 'PM', 'barre3', 'Signature', 'min']):
                        all_text = frame_text
                        logger.debug(f"Found schedule in iframe")
                        break
            except Exception as e:
                logger.debug(f"Error reading iframe: {e}")
        
        # If no iframe found with schedule, try main page
        if not all_text:
            all_text = await page.inner_text('body')
        
        lines = all_text.split('\n')
        
        current_class = {}
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Look for time pattern: "5:45 AM" or "12:00 PM"
            time_match = re.match(r'^(\d{1,2}:\d{2}\s*[AP]M)$', line, re.IGNORECASE)
            if time_match:
                # Save previous class if exists
                if current_class.get('name') and current_class.get('time'):
                    classes.append(Barre3Class(
                        name=current_class.get('name', ''),
                        time=current_class.get('time', ''),
                        date=date_str,
                        instructor=current_class.get('instructor', 'TBD'),
                        duration_minutes=current_class.get('duration', 45),
                        room=current_class.get('room', ''),
                        location=current_class.get('location', 'Seattle - Ballard')
                    ))
                
                # Start new class
                current_class = {
                    'time': parse_time_to_24h(time_match.group(1))
                }
                continue
            
            # Look for duration: "45 min." or "60 min"
            duration_match = re.match(r'^(\d+)\s*min\.?$', line, re.IGNORECASE)
            if duration_match:
                current_class['duration'] = int(duration_match.group(1))
                continue
            
            # Look for location: "Seattle - Ballard"
            if 'ballard' in line.lower() and 'seattle' in line.lower():
                current_class['location'] = line
                continue
            
            # Look for class names (contain "barre3")
            if 'barre3' in line.lower():
                if 'name' not in current_class or not current_class['name']:
                    current_class['name'] = line
                continue
            
            # Look for room/studio
            if 'studio' in line.lower() or 'livestream' in line.lower():
                current_class['room'] = line
                continue
            
            # Look for instructor (name pattern - capitalized words)
            name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)$', line)
            if name_match and 'instructor' not in current_class:
                potential_name = name_match.group(1)
                # Make sure it's not a class name or location
                if 'barre3' not in potential_name.lower() and 'seattle' not in potential_name.lower():
                    current_class['instructor'] = potential_name
                continue
        
        # Don't forget the last class
        if current_class.get('name') and current_class.get('time'):
            classes.append(Barre3Class(
                name=current_class.get('name', ''),
                time=current_class.get('time', ''),
                date=date_str,
                instructor=current_class.get('instructor', 'TBD'),
                duration_minutes=current_class.get('duration', 45),
                room=current_class.get('room', ''),
                location=current_class.get('location', 'Seattle - Ballard')
            ))
        
        # Filter out Livestream classes (you probably want in-person only)
        # Comment this out if you want to include Livestream
        classes = [c for c in classes if 'livestream' not in c.name.lower() and 'livestream' not in c.room.lower()]
        
    except Exception as e:
        logger.error(f"Error extracting barre3 classes: {e}")
        import traceback
        traceback.print_exc()
    
    return classes


# Fallback schedule
FALLBACK_SCHEDULE = {
    0: [  # Monday
        ("05:45", "barre3 Signature 45", 45, "Studio 1"),
        ("06:00", "barre3 Signature 45", 45, "Studio 2"),
        ("09:00", "barre3 Signature 60", 60, "Studio 1"),
        ("09:30", "barre3 Signature 45", 45, "Studio 2"),
        ("12:00", "barre3 Express 30", 30, "Studio 1"),
        ("16:30", "barre3 Signature 45", 45, "Studio 1"),
        ("17:45", "barre3 Signature 45", 45, "Studio 1"),
    ],
    1: [  # Tuesday
        ("05:45", "barre3 Signature 45", 45, "Studio 2"),
        ("06:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:30", "barre3 Cardio 45", 45, "Studio 2"),
        ("12:00", "barre3 Signature 45", 45, "Studio 1"),
        ("16:30", "barre3 Signature 45", 45, "Studio 1"),
        ("17:45", "barre3 Signature 45", 45, "Studio 2"),
    ],
    2: [  # Wednesday
        ("05:45", "barre3 Signature 45", 45, "Studio 1"),
        ("06:00", "barre3 Signature 45", 45, "Studio 2"),
        ("09:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:30", "barre3 Signature 45", 45, "Studio 2"),
        ("12:00", "barre3 Express 30", 30, "Studio 1"),
        ("16:30", "barre3 Signature 45", 45, "Studio 1"),
        ("17:45", "barre3 Cardio 45", 45, "Studio 1"),
    ],
    3: [  # Thursday
        ("05:45", "barre3 Signature 45", 45, "Studio 2"),
        ("06:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:30", "barre3 Signature 45", 45, "Studio 2"),
        ("12:00", "barre3 Signature 45", 45, "Studio 1"),
        ("16:30", "barre3 Signature 45", 45, "Studio 1"),
        ("17:45", "barre3 Signature 45", 45, "Studio 2"),
    ],
    4: [  # Friday
        ("05:45", "barre3 Signature 45", 45, "Studio 1"),
        ("06:00", "barre3 Signature 45", 45, "Studio 2"),
        ("09:00", "barre3 Cardio 45", 45, "Studio 1"),
        ("09:30", "barre3 Signature 45", 45, "Studio 2"),
        ("12:00", "barre3 Express 30", 30, "Studio 1"),
        ("16:00", "barre3 Signature 45", 45, "Studio 1"),
    ],
    5: [  # Saturday
        ("07:30", "barre3 Signature 45", 45, "Studio 1"),
        ("08:00", "barre3 Signature 45", 45, "Studio 2"),
        ("09:00", "barre3 Signature 60", 60, "Studio 1"),
        ("09:15", "barre3 Cardio 45", 45, "Studio 2"),
        ("10:30", "barre3 Signature 45", 45, "Studio 1"),
    ],
    6: [  # Sunday
        ("08:00", "barre3 Signature 45", 45, "Studio 1"),
        ("09:00", "barre3 Signature 60", 60, "Studio 1"),
        ("09:15", "barre3 Signature 45", 45, "Studio 2"),
        ("10:30", "barre3 Signature 45", 45, "Studio 1"),
    ],
}


def get_barre3_fallback_schedule(target_date: datetime) -> List[Dict]:
    """Get fallback schedule for a date."""
    weekday = target_date.weekday()
    date_str = target_date.strftime("%Y-%m-%d")
    
    classes = []
    for time, name, duration, room in FALLBACK_SCHEDULE.get(weekday, []):
        classes.append({
            "studio": "barre3",
            "class_name": name,
            "name": name,
            "time": time,
            "date": date_str,
            "instructor": "TBD",
            "duration_minutes": duration,
            "room": room,
            "location": "Seattle - Ballard"
        })
    
    return classes


# Test function
async def test_scraper():
    """Test the barre3 scraper."""
    logging.basicConfig(level=logging.INFO)
    
    print("Testing barre3 scraper...")
    print("=" * 50)
    
    classes = await scrape_barre3_schedule(days_ahead=3)
    
    if classes:
        print(f"\n✅ Found {len(classes)} classes:\n")
        current_date = ""
        for cls in classes:
            if cls.date != current_date:
                current_date = cls.date
                dt = datetime.strptime(cls.date, "%Y-%m-%d")
                print(f"\n{dt.strftime('%A, %B %d')}:")
                print("-" * 30)
            
            print(f"  {cls.time} - {cls.name} ({cls.duration_minutes} min)")
            print(f"         w/ {cls.instructor} | {cls.room}")
    else:
        print("\n❌ No classes found via scraping.")
        print("Using fallback schedule instead:\n")
        today = datetime.now(SEATTLE_TZ)
        for i in range(3):
            date = today + timedelta(days=i)
            fallback = get_barre3_fallback_schedule(date)
            print(f"\n{date.strftime('%A %m/%d')}:")
            for cls in fallback[:4]:
                print(f"  {cls['time']} - {cls['class_name']} ({cls['duration_minutes']} min)")


if __name__ == "__main__":
    asyncio.run(test_scraper())