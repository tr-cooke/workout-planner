"""
Solidcore Schedule Scraper
==========================

Scrapes the public schedule from solidcore.co/studios/ballard
No login required - the schedule is publicly visible.

Usage:
    python integrations/solidcore_scraper.py
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
class SolidcoreClass:
    """Represents a solidcore class."""
    name: str  # e.g., "Signature50: Full Body", "Arms & Abs"
    time: str  # e.g., "12:10" (24-hour format)
    end_time: str  # e.g., "13:00"
    date: str  # e.g., "2026-03-10"
    instructor: str
    duration_minutes: int
    spots_available: Optional[int] = None
    spots_total: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "studio": "solidcore",
            "class_name": self.name,
            "name": self.name,
            "time": self.time,
            "end_time": self.end_time,
            "date": self.date,
            "instructor": self.instructor,
            "duration_minutes": self.duration_minutes,
            "spots_available": self.spots_available,
            "spots_total": self.spots_total
        }


def parse_time_to_24h(time_str: str) -> str:
    """Convert '12:10 PM' to '12:10' (24-hour format)."""
    time_str = time_str.strip()
    try:
        # Try parsing "12:10 PM" format
        dt = datetime.strptime(time_str, "%I:%M %p")
        return dt.strftime("%H:%M")
    except ValueError:
        try:
            # Try parsing "12:10PM" format (no space)
            dt = datetime.strptime(time_str, "%I:%M%p")
            return dt.strftime("%H:%M")
        except ValueError:
            # Already in 24-hour format or unknown
            return time_str


async def scrape_solidcore_schedule(days_ahead: int = 7) -> List[SolidcoreClass]:
    """
    Scrape solidcore Ballard schedule.
    
    Args:
        days_ahead: Number of days to fetch (default 7)
        
    Returns:
        List of SolidcoreClass objects
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available")
        return []
    
    all_classes = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            logger.info("Loading solidcore Ballard page...")
            await page.goto("https://solidcore.co/studios/ballard", wait_until="networkidle")
            
            # Wait for the schedule to load (it's loaded via JavaScript)
            await page.wait_for_timeout(3000)
            
            # Scrape multiple days by clicking on date buttons
            for day_offset in range(min(days_ahead, 14)):  # Max 2 weeks shown
                target_date = datetime.now(SEATTLE_TZ) + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")
                day_num = target_date.day
                
                logger.info(f"Scraping {target_date.strftime('%A %m/%d')}...")
                
                # Click on the day button if not the first day
                if day_offset > 0:
                    # Find and click the date button
                    # The buttons show the day number (e.g., "10", "11")
                    day_buttons = await page.query_selector_all('button, div[role="button"], [class*="day"], [class*="date"]')
                    
                    for btn in day_buttons:
                        try:
                            text = await btn.inner_text()
                            # Look for button with just the day number
                            if text.strip() == str(day_num) or f"\n{day_num}\n" in text or text.endswith(f"\n{day_num}"):
                                await btn.click()
                                await page.wait_for_timeout(2000)  # Wait for schedule to update
                                break
                        except:
                            pass
                
                # Now extract classes for this day
                classes_for_day = await extract_classes_from_page(page, date_str)
                all_classes.extend(classes_for_day)
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping solidcore: {e}")
        import traceback
        traceback.print_exc()
    
    return all_classes


async def extract_classes_from_page(page, date_str: str) -> List[SolidcoreClass]:
    """Extract class information from the current page state."""
    classes = []
    
    try:
        # Get all text content and parse it
        # Look for patterns like "12:10 PM - 1:00 PM" and "Signature50: Full Body"
        
        # Find all elements that look like class rows
        # Based on the screenshot, each class has: time range, class name, location, instructor, availability
        
        # Try to find class containers - look for elements containing time patterns
        all_text = await page.inner_text('body')
        
        # Split by lines and look for class patterns
        lines = all_text.split('\n')
        
        current_class = {}
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Look for time pattern: "12:10 PM - 1:00 PM"
            time_match = re.match(r'(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)', line)
            if time_match:
                # Save previous class if exists
                if current_class.get('name') and current_class.get('time'):
                    classes.append(SolidcoreClass(
                        name=current_class.get('name', ''),
                        time=current_class.get('time', ''),
                        end_time=current_class.get('end_time', ''),
                        date=date_str,
                        instructor=current_class.get('instructor', 'TBD'),
                        duration_minutes=current_class.get('duration', 50),
                        spots_available=current_class.get('spots_available'),
                        spots_total=current_class.get('spots_total')
                    ))
                
                # Start new class
                start_time = parse_time_to_24h(time_match.group(1))
                end_time = parse_time_to_24h(time_match.group(2))
                
                # Calculate duration
                try:
                    start_dt = datetime.strptime(start_time, "%H:%M")
                    end_dt = datetime.strptime(end_time, "%H:%M")
                    duration = int((end_dt - start_dt).total_seconds() / 60)
                except:
                    duration = 50
                
                current_class = {
                    'time': start_time,
                    'end_time': end_time,
                    'duration': duration
                }
                continue
            
            # Look for class name (contains "Signature" or known class types)
            if any(x in line for x in ['Signature', 'Arms', 'Lower Body', 'Full Body', 'Core', 'Upper']):
                if 'name' not in current_class or not current_class['name']:
                    current_class['name'] = line
                continue
            
            # Look for instructor pattern: "w/ Name"
            instructor_match = re.match(r'w/\s*(.+)', line)
            if instructor_match:
                current_class['instructor'] = instructor_match.group(1).strip()
                continue
            
            # Look for availability: "6 of 15 open"
            avail_match = re.match(r'(\d+)\s+of\s+(\d+)\s+open', line)
            if avail_match:
                current_class['spots_available'] = int(avail_match.group(1))
                current_class['spots_total'] = int(avail_match.group(2))
                continue
        
        # Don't forget the last class
        if current_class.get('name') and current_class.get('time'):
            classes.append(SolidcoreClass(
                name=current_class.get('name', ''),
                time=current_class.get('time', ''),
                end_time=current_class.get('end_time', ''),
                date=date_str,
                instructor=current_class.get('instructor', 'TBD'),
                duration_minutes=current_class.get('duration', 50),
                spots_available=current_class.get('spots_available'),
                spots_total=current_class.get('spots_total')
            ))
        
    except Exception as e:
        logger.error(f"Error extracting classes: {e}")
    
    return classes


async def get_solidcore_classes_for_date(target_date: datetime) -> List[Dict]:
    """Get solidcore classes for a specific date."""
    all_classes = await scrape_solidcore_schedule(days_ahead=14)
    
    target_str = target_date.strftime("%Y-%m-%d")
    return [c.to_dict() for c in all_classes if c.date == target_str]


async def get_solidcore_classes_for_date(target_date: datetime) -> List[Dict]:
    """Get solidcore classes for a specific date."""
    all_classes = await scrape_solidcore_schedule()
    
    target_str = target_date.strftime("%Y-%m-%d")
    return [c.to_dict() for c in all_classes if c.date == target_str]


# Fallback schedule when scraping fails
FALLBACK_SCHEDULE = {
    0: [  # Monday
        ("06:00", "Signature50: Full Body", 50),
        ("07:00", "Signature50: Full Body", 50),
        ("09:30", "Signature50: Full Body", 50),
        ("12:00", "Signature50: Full Body", 50),
        ("17:30", "Signature50: Full Body", 50),
        ("18:30", "Signature50: Full Body", 50),
    ],
    1: [  # Tuesday
        ("06:00", "Signature50: Full Body", 50),
        ("07:00", "Arms & Abs", 50),
        ("09:30", "Signature50: Full Body", 50),
        ("12:00", "Signature50: Full Body", 50),
        ("17:30", "Signature50: Full Body", 50),
        ("18:30", "Lower Body", 50),
    ],
    2: [  # Wednesday
        ("06:00", "Signature50: Full Body", 50),
        ("07:00", "Signature50: Full Body", 50),
        ("09:30", "Signature50: Full Body", 50),
        ("12:00", "Signature50: Full Body", 50),
        ("17:30", "Signature50: Full Body", 50),
        ("18:30", "Signature50: Full Body", 50),
    ],
    3: [  # Thursday
        ("06:00", "Signature50: Full Body", 50),
        ("07:00", "Lower Body", 50),
        ("09:30", "Signature50: Full Body", 50),
        ("12:00", "Signature50: Full Body", 50),
        ("17:30", "Signature50: Full Body", 50),
        ("18:30", "Arms & Abs", 50),
    ],
    4: [  # Friday
        ("06:00", "Signature50: Full Body", 50),
        ("07:00", "Signature50: Full Body", 50),
        ("09:30", "Signature50: Full Body", 50),
        ("12:00", "Signature50: Full Body", 50),
        ("17:00", "Signature50: Full Body", 50),
    ],
    5: [  # Saturday
        ("08:00", "Signature50: Full Body", 50),
        ("09:00", "Signature50: Full Body", 50),
        ("10:00", "Signature50: Full Body", 50),
        ("11:00", "Signature50: Full Body", 50),
    ],
    6: [  # Sunday
        ("08:00", "Signature50: Full Body", 50),
        ("09:00", "Signature50: Full Body", 50),
        ("10:00", "Signature50: Full Body", 50),
        ("11:00", "Signature50: Full Body", 50),
    ],
}


def get_fallback_schedule(target_date: datetime) -> List[Dict]:
    """Get fallback schedule for a date."""
    weekday = target_date.weekday()
    date_str = target_date.strftime("%Y-%m-%d")
    
    classes = []
    for time, name, duration in FALLBACK_SCHEDULE.get(weekday, []):
        classes.append({
            "studio": "solidcore",
            "class_name": name,
            "name": name,
            "time": time,
            "date": date_str,
            "instructor": "TBD",
            "duration_minutes": duration
        })
    
    return classes


# Test function
async def test_scraper():
    """Test the solidcore scraper."""
    logging.basicConfig(level=logging.INFO)
    
    print("Testing solidcore scraper...")
    print("=" * 50)
    
    classes = await scrape_solidcore_schedule(days_ahead=3)
    
    if classes:
        print(f"\n✅ Found {len(classes)} classes:\n")
        current_date = ""
        for cls in classes:
            if cls.date != current_date:
                current_date = cls.date
                # Parse date for display
                dt = datetime.strptime(cls.date, "%Y-%m-%d")
                print(f"\n{dt.strftime('%A, %B %d')}:")
                print("-" * 30)
            
            spots = f"({cls.spots_available}/{cls.spots_total} spots)" if cls.spots_available else ""
            print(f"  {cls.time} - {cls.name} w/ {cls.instructor} {spots}")
    else:
        print("\n❌ No classes found via scraping.")
        print("Using fallback schedule instead:\n")
        today = datetime.now()
        for i in range(3):
            date = today + timedelta(days=i)
            fallback = get_fallback_schedule(date)
            print(f"\n{date.strftime('%A %m/%d')}:")
            for cls in fallback[:5]:
                print(f"  {cls['time']} - {cls['class_name']}")


if __name__ == "__main__":
    asyncio.run(test_scraper())
