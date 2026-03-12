"""
Ballard Pool Schedule Scraper
=============================

Scrapes the lap swim schedule from Seattle.gov Ballard Pool page.
The schedule is a static HTML table that changes seasonally (2-3x per year).

Usage:
    python integrations/pool_scraper.py
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
class PoolSession:
    """Represents a lap swim session at Ballard Pool."""
    name: str  # e.g., "Early Morning Lap Swim (EMLS)", "Lap Swim"
    time_start: str  # e.g., "06:00" (24-hour format)
    time_end: str  # e.g., "07:30"
    days: List[str]  # e.g., ["Mon", "Wed", "Fri"]
    details: str  # e.g., "Six lap lanes"
    
    def to_dict(self) -> dict:
        return {
            "studio": "pool",
            "class_name": self.name,
            "name": self.name,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "days": self.days,
            "details": self.details
        }


def parse_time_range(time_str: str) -> tuple:
    """
    Parse time range like '6:00am-7:30am' or '1:30pm-2:30pm' to 24-hour format.
    Returns (start_time, end_time) as strings like ('06:00', '07:30')
    """
    time_str = time_str.strip().lower().replace(" ", "")
    
    # Handle various formats
    # "6:00am-7:30am", "6:00am-7:30am*", "1:30pm-2:30pm"
    time_str = re.sub(r'\*.*$', '', time_str)  # Remove asterisks and notes
    
    match = re.match(r'(\d{1,2}):?(\d{2})?(am|pm)?[-–to]+(\d{1,2}):?(\d{2})?(am|pm)?', time_str)
    if not match:
        return ("00:00", "00:00")
    
    start_hour = int(match.group(1))
    start_min = int(match.group(2) or 0)
    start_ampm = match.group(3)
    end_hour = int(match.group(4))
    end_min = int(match.group(5) or 0)
    end_ampm = match.group(6) or start_ampm  # If end has no am/pm, use start's
    
    # Convert to 24-hour
    if start_ampm == 'pm' and start_hour != 12:
        start_hour += 12
    elif start_ampm == 'am' and start_hour == 12:
        start_hour = 0
        
    if end_ampm == 'pm' and end_hour != 12:
        end_hour += 12
    elif end_ampm == 'am' and end_hour == 12:
        end_hour = 0
    
    return (f"{start_hour:02d}:{start_min:02d}", f"{end_hour:02d}:{end_min:02d}")


def parse_days(day_str: str) -> List[str]:
    """
    Parse day string like 'Mon, Wed, Fri' or 'Mon-Fri' to list of day abbreviations.
    """
    day_str = day_str.strip()
    
    all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_map = {
        "monday": "Mon", "mon": "Mon", "m": "Mon",
        "tuesday": "Tue", "tue": "Tue", "tues": "Tue", "tu": "Tue",
        "wednesday": "Wed", "wed": "Wed", "w": "Wed",
        "thursday": "Thu", "thu": "Thu", "thur": "Thu", "thurs": "Thu", "th": "Thu",
        "friday": "Fri", "fri": "Fri", "f": "Fri",
        "saturday": "Sat", "sat": "Sat", "sa": "Sat",
        "sunday": "Sun", "sun": "Sun", "su": "Sun"
    }
    
    # Handle ranges like "Mon-Fri"
    if "-" in day_str and "," not in day_str:
        parts = day_str.lower().split("-")
        if len(parts) == 2:
            start_day = day_map.get(parts[0].strip())
            end_day = day_map.get(parts[1].strip())
            if start_day and end_day:
                start_idx = all_days.index(start_day)
                end_idx = all_days.index(end_day)
                return all_days[start_idx:end_idx + 1]
    
    # Handle comma-separated lists like "Mon, Wed, Fri"
    days = []
    for part in re.split(r'[,&]', day_str):
        part = part.strip().lower()
        if part in day_map:
            days.append(day_map[part])
    
    return days if days else []


async def scrape_pool_schedule() -> List[PoolSession]:
    """
    Scrape Ballard Pool lap swim schedule from Seattle.gov.
    
    Returns:
        List of PoolSession objects
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available")
        return []
    
    sessions = []
    
    try:
        async with async_playwright() as p:
            # Use a real browser user agent to avoid bot detection
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )
            page = await context.new_page()
            
            # Set extra headers to look more like a real browser
            await page.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            })
            
            logger.info("Loading Ballard Pool schedule page...")
            await page.goto("https://www.seattle.gov/parks/pools/ballard-pool", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            
            # Look for the schedule table - it has headers: Program, Day, Time, Details
            # Try to find tables on the page
            tables = await page.query_selector_all('table')
            logger.info(f"Found {len(tables)} tables")
            
            for table in tables:
                table_text = await table.inner_text()
                
                # Check if this is the schedule table (contains "Program" and "Lap Swim")
                if 'Program' in table_text and 'Lap Swim' in table_text:
                    logger.info("Found schedule table")
                    
                    # Get all rows
                    rows = await table.query_selector_all('tr')
                    
                    current_program = ""
                    
                    for row in rows:
                        cells = await row.query_selector_all('td, th')
                        cell_texts = []
                        for cell in cells:
                            text = await cell.inner_text()
                            cell_texts.append(text.strip())
                        
                        if not cell_texts or all(not c for c in cell_texts):
                            continue
                        
                        # Skip header row
                        if 'Program' in cell_texts[0] and 'Day' in cell_texts:
                            continue
                        
                        # Parse the row - format is: Program, Day, Time, Details
                        # Some rows may have empty Program (continuation of previous)
                        # Rows can have 3 or 4 columns
                        # 4 columns: [Program, Day, Time, Details]
                        # 3 columns: [Day, Time, Details] - continuation of previous program
                        
                        if len(cell_texts) == 4:
                            # Full row with program name
                            program = cell_texts[0]
                            day_str = cell_texts[1]
                            time_str = cell_texts[2]
                            details = cell_texts[3]
                            
                            if program:
                                current_program = program
                                
                        elif len(cell_texts) == 3:
                            # Continuation row - no program column
                            day_str = cell_texts[0]
                            time_str = cell_texts[1]
                            details = cell_texts[2] if len(cell_texts) > 2 else ""
                            
                        elif len(cell_texts) == 2:
                            # Minimal row - just day and time
                            day_str = cell_texts[0]
                            time_str = cell_texts[1]
                            details = ""
                        else:
                            continue
                        
                        # Use current_program for the session
                        session_program = current_program
                        
                        if not session_program:
                            continue
                            
                        # Include lap swim, water exercise, adult swim, and recreation/lap combo
                        program_lower = session_program.lower()
                        is_lap_swim = 'lap swim' in program_lower or 'lap' in program_lower
                        is_water_exercise = 'water exercise' in program_lower or 'deep water' in program_lower or 'shallow water' in program_lower
                        is_adult_swim = 'adult' in program_lower or 'senior' in program_lower
                        is_recreation_lap = 'recreation' in program_lower and 'lap' in program_lower
                        
                        if is_lap_swim or is_water_exercise or is_adult_swim or is_recreation_lap:
                            if day_str and time_str:
                                # Skip notes/exceptions like "***Jan. 9, 16..."
                                if time_str.startswith('*'):
                                    continue
                                
                                # Clean up time string (remove notes after newlines)
                                time_str = time_str.split('\n')[0].strip()
                                
                                days = parse_days(day_str)
                                time_start, time_end = parse_time_range(time_str)
                                
                                if days and time_start != "00:00":
                                    session = PoolSession(
                                        name=session_program,
                                        time_start=time_start,
                                        time_end=time_end,
                                        days=days,
                                        details=details
                                    )
                                    sessions.append(session)
                                    logger.info(f"  Found: {session_program} - {days} @ {time_start}-{time_end}")
                    
                    break  # Found the schedule table, no need to check others
            
            # If no table found, try parsing text directly
            if not sessions:
                logger.info("No table found, trying text extraction...")
                page_text = await page.inner_text('body')
                sessions = parse_schedule_from_text(page_text)
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping Ballard Pool: {e}")
        import traceback
        traceback.print_exc()
    
    return sessions


def parse_schedule_from_text(text: str) -> List[PoolSession]:
    """Fallback: parse schedule from page text."""
    sessions = []
    
    # Look for patterns like "Early Morning Lap Swim" followed by days and times
    lines = text.split('\n')
    
    current_program = ""
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Check if this line is a program name
        if 'lap swim' in line.lower():
            current_program = line
            continue
        
        # Look for day patterns on lines after program name
        if current_program:
            # Try to find "Mon, Wed, Fri" or "Mon-Fri" patterns
            day_match = re.search(r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:[\s,&-]+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))*)', line, re.IGNORECASE)
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?\s*[-–to]+\s*\d{1,2}:\d{2}\s*(?:am|pm)?)', line, re.IGNORECASE)
            
            if day_match and time_match:
                days = parse_days(day_match.group(1))
                time_start, time_end = parse_time_range(time_match.group(1))
                
                if days and time_start != "00:00":
                    sessions.append(PoolSession(
                        name=current_program,
                        time_start=time_start,
                        time_end=time_end,
                        days=days,
                        details=""
                    ))
    
    return sessions


def get_pool_classes_for_date(sessions: List[PoolSession], target_date: datetime) -> List[Dict]:
    """Convert pool sessions to class list for a specific date."""
    day_name = target_date.strftime("%a")  # "Mon", "Tue", etc.
    date_str = target_date.strftime("%Y-%m-%d")
    
    classes = []
    for session in sessions:
        if day_name in session.days:
            # Calculate duration in minutes
            start_parts = session.time_start.split(":")
            end_parts = session.time_end.split(":")
            start_mins = int(start_parts[0]) * 60 + int(start_parts[1])
            end_mins = int(end_parts[0]) * 60 + int(end_parts[1])
            duration = end_mins - start_mins
            
            classes.append({
                "studio": "pool",
                "class_name": session.name,
                "name": session.name,
                "time": session.time_start,
                "time_end": session.time_end,
                "date": date_str,
                "duration_minutes": duration,
                "details": session.details,
                "instructor": ""
            })
    
    return classes


# Fallback schedule based on the screenshot
FALLBACK_SESSIONS = [
    PoolSession(
        name="Early Morning Lap Swim (EMLS)",
        time_start="06:00",
        time_end="07:30",
        days=["Mon", "Wed", "Fri"],
        details="Six lap lanes. Payment with Quick Card, check, or exact change only."
    ),
    PoolSession(
        name="Lap Swim",
        time_start="08:45",
        time_end="09:45",
        days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        details="Five lap lanes."
    ),
    PoolSession(
        name="Lap Swim",
        time_start="13:30",
        time_end="14:30",
        days=["Mon", "Tue", "Thu", "Fri"],
        details="Four lap lanes with an open section for water walking."
    ),
    PoolSession(
        name="Lap Swim",
        time_start="19:45",
        time_end="20:45",
        days=["Mon", "Wed"],
        details="Evening lap swim. Six lap lanes."
    ),
    PoolSession(
        name="Lap Swim",
        time_start="17:30",
        time_end="18:45",
        days=["Sat"],
        details="Weekend lap swim."
    ),
]


def get_fallback_pool_schedule(target_date: datetime) -> List[Dict]:
    """Get fallback schedule for a date."""
    return get_pool_classes_for_date(FALLBACK_SESSIONS, target_date)


# Test function
async def test_scraper():
    """Test the Ballard Pool scraper."""
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Ballard Pool scraper...")
    print("=" * 50)
    
    sessions = await scrape_pool_schedule()
    
    if sessions:
        print(f"\n✅ Found {len(sessions)} lap swim sessions:\n")
        for session in sessions:
            print(f"  {session.name}")
            print(f"    Days: {', '.join(session.days)}")
            print(f"    Time: {session.time_start} - {session.time_end}")
            print(f"    Details: {session.details}")
            print()
        
        # Show schedule for the next 3 days
        print("\nSchedule for next 3 days:")
        print("-" * 30)
        today = datetime.now(SEATTLE_TZ)
        for i in range(3):
            date = today + timedelta(days=i)
            classes = get_pool_classes_for_date(sessions, date)
            print(f"\n{date.strftime('%A %m/%d')}:")
            if classes:
                for cls in classes:
                    print(f"  {cls['time']}-{cls['time_end']} - {cls['class_name']}")
            else:
                print("  No lap swim sessions")
    else:
        print("\n❌ No sessions found via scraping.")
        print("Using fallback schedule:\n")
        today = datetime.now(SEATTLE_TZ)
        for i in range(3):
            date = today + timedelta(days=i)
            classes = get_fallback_pool_schedule(date)
            print(f"\n{date.strftime('%A %m/%d')}:")
            if classes:
                for cls in classes:
                    print(f"  {cls['time']}-{cls['time_end']} - {cls['class_name']}")
            else:
                print("  No lap swim sessions")


if __name__ == "__main__":
    asyncio.run(test_scraper())