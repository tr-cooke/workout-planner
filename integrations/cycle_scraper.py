"""
Cycle Sanctuary Schedule Scraper
================================

Scrapes the public schedule from thecyclesanctuary.com/schedule
No login required - the schedule is publicly visible.

Usage:
    python integrations/cycle_scraper.py
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
    logger.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")


@dataclass
class CycleClass:
    """Represents a Cycle Sanctuary class."""
    name: str  # e.g., "Power Cycle 45", "Strength & Stability 60 - PULL"
    time: str  # e.g., "06:30" (24-hour format)
    date: str  # e.g., "2026-03-10"
    instructor: str
    duration_minutes: int
    studio_type: str  # "Cycle Studio" or "Bootcamp Studio"
    location: str  # "Ballard"
    
    def to_dict(self) -> dict:
        return {
            "studio": "cycle",
            "class_name": self.name,
            "name": self.name,
            "time": self.time,
            "date": self.date,
            "instructor": self.instructor,
            "duration_minutes": self.duration_minutes,
            "studio_type": self.studio_type,
            "location": self.location
        }


def parse_time_to_24h(time_str: str) -> str:
    """Convert '6:30 AM' or '12:00 PM' to '06:30' or '12:00' (24-hour format)."""
    time_str = time_str.strip().upper()
    try:
        # Try parsing "6:30 AM" format
        dt = datetime.strptime(time_str, "%I:%M %p")
        return dt.strftime("%H:%M")
    except ValueError:
        try:
            # Try parsing "6:30AM" format (no space)
            dt = datetime.strptime(time_str, "%I:%M%p")
            return dt.strftime("%H:%M")
        except ValueError:
            # Already in 24-hour format or unknown
            return time_str


def parse_duration(duration_str: str) -> int:
    """Parse '60 min.' or '45 min.' to integer minutes."""
    match = re.search(r'(\d+)\s*min', duration_str.lower())
    if match:
        return int(match.group(1))
    return 45  # Default


async def scrape_cycle_schedule(days_ahead: int = 7) -> List[CycleClass]:
    """
    Scrape Cycle Sanctuary Ballard schedule.
    
    Args:
        days_ahead: Number of days to fetch (default 7)
        
    Returns:
        List of CycleClass objects
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available")
        return []
    
    all_classes = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Use the direct Mariana Tek schedule URL
            # Location ID 48717 is Ballard, 48541 is the brand ID
            base_url = "https://www.thecyclesanctuary.com/schedule?_mt=%2Fschedule%2Fdaily%2F48541"
            
            for day_offset in range(min(days_ahead, 7)):
                target_date = datetime.now(SEATTLE_TZ) + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")
                
                # Build URL with specific date
                url = f"{base_url}%3FactiveDate%3D{date_str}%26locations%3D48717"
                
                logger.info(f"Loading schedule for {target_date.strftime('%A %m/%d')}...")
                await page.goto(url, wait_until="networkidle")
                
                # Wait for content to load
                await page.wait_for_timeout(3000)
                
                # Close ALL popups on first load
                if day_offset == 0:
                    # Close promotional popup (X button)
                    for _ in range(3):  # Try multiple times
                        try:
                            close_btn = await page.query_selector('[aria-label="Close"]')
                            if close_btn:
                                await close_btn.click()
                                logger.info("Closed promotional popup")
                                await page.wait_for_timeout(500)
                        except:
                            pass
                        
                        # Press Escape
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(300)
                    
                    # Click Accept on cookie consent
                    try:
                        accept_btn = await page.query_selector('text="Accept"')
                        if accept_btn:
                            await accept_btn.click()
                            logger.info("Clicked Accept on cookie popup")
                            await page.wait_for_timeout(500)
                    except:
                        pass
                    
                    # Wait for popups to fully close
                    await page.wait_for_timeout(1000)
                
                # Now extract classes from this day
                classes_for_day = await extract_cycle_classes(page, date_str)
                all_classes.extend(classes_for_day)
                
                logger.info(f"  Found {len(classes_for_day)} classes")
            
            # Save debug screenshot
            await page.screenshot(path='/tmp/cycle_debug.png')
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping Cycle Sanctuary: {e}")
        import traceback
        traceback.print_exc()
    
    return all_classes


async def extract_cycle_classes(page, date_str: str) -> List[CycleClass]:
    """Extract class information from the current page state."""
    classes = []
    
    try:
        # The schedule is in a Mariana Tek iframe - we need to find it
        all_text = ""
        
        # First try to find the iframe
        iframes = await page.query_selector_all('iframe')
        for iframe in iframes:
            try:
                frame = await iframe.content_frame()
                if frame:
                    frame_text = await frame.inner_text('body')
                    # Check if this iframe has schedule content
                    if any(x in frame_text for x in ['AM', 'PM', 'Cycle', 'Strength', 'RESERVE']):
                        all_text = frame_text
                        logger.debug(f"Found schedule in iframe, text length: {len(all_text)}")
                        break
            except Exception as e:
                logger.debug(f"Error reading iframe: {e}")
        
        # If no iframe found with schedule, try main page
        if not all_text:
            all_text = await page.inner_text('body')
        
        logger.debug(f"Extracted text (first 500): {all_text[:500]}")
        
        lines = all_text.split('\n')
        
        current_class = {}
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Look for time pattern: "6:30 AM" or "12:00 PM"
            time_match = re.match(r'^(\d{1,2}:\d{2}\s*[AP]M)$', line, re.IGNORECASE)
            if time_match:
                # Save previous class if exists
                if current_class.get('name') and current_class.get('time'):
                    classes.append(CycleClass(
                        name=current_class.get('name', ''),
                        time=current_class.get('time', ''),
                        date=date_str,
                        instructor=current_class.get('instructor', 'TBD'),
                        duration_minutes=current_class.get('duration', 45),
                        studio_type=current_class.get('studio_type', ''),
                        location=current_class.get('location', 'Ballard')
                    ))
                
                # Start new class
                current_class = {
                    'time': parse_time_to_24h(time_match.group(1))
                }
                continue
            
            # Look for duration: "60 min." or "45 min" or "60 min"
            duration_match = re.match(r'^(\d+)\s*min\.?$', line, re.IGNORECASE)
            if duration_match:
                current_class['duration'] = int(duration_match.group(1))
                continue
            
            # Look for location: "Ballard"
            if line.lower() == 'ballard':
                current_class['location'] = 'Ballard'
                continue
            
            # Look for class names (contain keywords like Cycle, Strength, HIIT, Power, Release, Restore)
            if any(x in line for x in ['Cycle', 'Strength', 'HIIT', 'Power', 'PULL', 'PUSH', 'Endurance', 'Recovery', 'Release', 'Restore']):
                # Make sure it's not the studio type or a nav element
                if 'Studio' not in line and 'The Cycle' not in line:
                    if 'name' not in current_class or not current_class['name']:
                        current_class['name'] = line
                continue
            
            # Look for studio type
            if 'Studio' in line and len(line) < 30:
                current_class['studio_type'] = line
                continue
            
            # Look for instructor (name pattern - capitalized words, not a class name)
            # Usually follows class name, 2-3 words
            name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)$', line)
            if name_match and 'instructor' not in current_class:
                potential_name = name_match.group(1)
                # Make sure it's not a class name or navigation
                if not any(x in potential_name for x in ['Cycle', 'Strength', 'HIIT', 'Power', 'Studio', 'The', 'About', 'Class']):
                    current_class['instructor'] = potential_name
                continue
        
        # Don't forget the last class
        if current_class.get('name') and current_class.get('time'):
            classes.append(CycleClass(
                name=current_class.get('name', ''),
                time=current_class.get('time', ''),
                date=date_str,
                instructor=current_class.get('instructor', 'TBD'),
                duration_minutes=current_class.get('duration', 45),
                studio_type=current_class.get('studio_type', ''),
                location=current_class.get('location', 'Ballard')
            ))
        
    except Exception as e:
        logger.error(f"Error extracting Cycle classes: {e}")
    
    return classes


async def get_cycle_classes_for_date(target_date: datetime) -> List[Dict]:
    """Get Cycle Sanctuary classes for a specific date."""
    all_classes = await scrape_cycle_schedule(days_ahead=7)
    
    target_str = target_date.strftime("%Y-%m-%d")
    return [c.to_dict() for c in all_classes if c.date == target_str]


# Fallback schedule when scraping fails
FALLBACK_SCHEDULE = {
    0: [  # Monday
        ("06:30", "Power Cycle 45", 45, "Cycle Studio"),
        ("09:00", "Strength & Stability 60", 60, "Bootcamp Studio"),
        ("12:00", "HIIT Cycle 45", 45, "Cycle Studio"),
        ("17:30", "Power Cycle 45", 45, "Cycle Studio"),
        ("18:30", "Strength & Stability 45", 45, "Bootcamp Studio"),
    ],
    1: [  # Tuesday
        ("06:30", "Strength & Stability 60 - PULL", 60, "Bootcamp Studio"),
        ("12:00", "STRENGTH / HIIT Cycle 45 - PULL", 45, "Bootcamp Studio"),
        ("17:30", "Strength & Stability 45 - PULL", 45, "Bootcamp Studio"),
        ("18:30", "Power Cycle 45", 45, "Cycle Studio"),
    ],
    2: [  # Wednesday
        ("06:30", "Power Cycle 45", 45, "Cycle Studio"),
        ("09:00", "Endurance Cycle 60", 60, "Cycle Studio"),
        ("12:00", "HIIT Cycle 45", 45, "Cycle Studio"),
        ("17:30", "Power Cycle 45", 45, "Cycle Studio"),
        ("18:30", "Strength & Stability 45", 45, "Bootcamp Studio"),
    ],
    3: [  # Thursday
        ("06:30", "Strength & Stability 60 - PUSH", 60, "Bootcamp Studio"),
        ("12:00", "STRENGTH / HIIT Cycle 45 - PUSH", 45, "Bootcamp Studio"),
        ("17:30", "Strength & Stability 45 - PUSH", 45, "Bootcamp Studio"),
        ("18:30", "Power Cycle 45", 45, "Cycle Studio"),
    ],
    4: [  # Friday
        ("06:30", "Power Cycle 45", 45, "Cycle Studio"),
        ("09:00", "Recovery Cycle 45", 45, "Cycle Studio"),
        ("12:00", "HIIT Cycle 45", 45, "Cycle Studio"),
        ("17:00", "Power Cycle 45", 45, "Cycle Studio"),
    ],
    5: [  # Saturday
        ("08:00", "Endurance Cycle 60", 60, "Cycle Studio"),
        ("09:15", "Strength & Stability 60", 60, "Bootcamp Studio"),
        ("10:30", "Power Cycle 45", 45, "Cycle Studio"),
    ],
    6: [  # Sunday
        ("09:00", "Recovery Cycle 45", 45, "Cycle Studio"),
        ("10:00", "Strength & Stability 60", 60, "Bootcamp Studio"),
    ],
}


def get_cycle_fallback_schedule(target_date: datetime) -> List[Dict]:
    """Get fallback schedule for a date."""
    weekday = target_date.weekday()
    date_str = target_date.strftime("%Y-%m-%d")
    
    classes = []
    for time, name, duration, studio_type in FALLBACK_SCHEDULE.get(weekday, []):
        classes.append({
            "studio": "cycle",
            "class_name": name,
            "name": name,
            "time": time,
            "date": date_str,
            "instructor": "TBD",
            "duration_minutes": duration,
            "studio_type": studio_type,
            "location": "Ballard"
        })
    
    return classes


# Test function
async def test_scraper():
    """Test the Cycle Sanctuary scraper."""
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Cycle Sanctuary scraper...")
    print("=" * 50)
    
    classes = await scrape_cycle_schedule(days_ahead=3)
    
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
            print(f"         w/ {cls.instructor} | {cls.studio_type}")
    else:
        print("\n❌ No classes found via scraping.")
        print("Using fallback schedule instead:\n")
        today = datetime.now(SEATTLE_TZ)
        for i in range(3):
            date = today + timedelta(days=i)
            fallback = get_cycle_fallback_schedule(date)
            print(f"\n{date.strftime('%A %m/%d')}:")
            for cls in fallback[:4]:
                print(f"  {cls['time']} - {cls['class_name']} ({cls['duration_minutes']} min)")


if __name__ == "__main__":
    asyncio.run(test_scraper())