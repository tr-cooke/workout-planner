"""
Playwright Browser Automation for Fitness Schedules
====================================================

This module handles browser-based scraping for studios that don't have APIs.

Setup Instructions:
1. Install Playwright:
   pip install playwright
   
2. Install browser binaries:
   playwright install chromium
   
   For Railway/Docker deployment:
   playwright install chromium --with-deps

3. For solidcore (requires login), set environment variables:
   - SOLIDCORE_EMAIL: Your solidcore account email
   - SOLIDCORE_PASSWORD: Your solidcore account password

Note: Browser automation is slower and more fragile than APIs.
Use APIs (Mindbody, Meetup) when available.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)

# Check if Playwright is available
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")


@dataclass
class ScrapedClass:
    """Generic class info from scraping."""
    studio: str
    name: str
    time: str
    date: str
    instructor: Optional[str] = None
    duration_minutes: Optional[int] = None
    spots_available: Optional[int] = None
    is_bookable: bool = True
    url: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "studio": self.studio,
            "name": self.name,
            "time": self.time,
            "date": self.date,
            "instructor": self.instructor,
            "duration_minutes": self.duration_minutes,
            "spots_available": self.spots_available,
            "is_bookable": self.is_bookable,
            "url": self.url
        }


class PlaywrightManager:
    """
    Manages Playwright browser instances for scraping.
    
    Reuses browser context across scrapes to improve performance.
    """
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
    
    async def start(self):
        """Start the browser."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed")
        
        if self.browser is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',  # Important for Docker/Railway
                ]
            )
            logger.info("Playwright browser started")
    
    async def stop(self):
        """Stop the browser."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        logger.info("Playwright browser stopped")
    
    async def new_context(self) -> BrowserContext:
        """Create a new browser context."""
        if not self.browser:
            await self.start()
        
        return await self.browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )


# Global browser manager (reused across scrapes)
browser_manager = PlaywrightManager()


class SolidcoreScraper:
    """
    Scraper for solidcore Ballard.
    
    Requires authentication to view schedule.
    Schedule releases on the 23rd (members) / 25th (public) of each month.
    """
    
    LOGIN_URL = "https://solidcore.co/auth"
    SCHEDULE_URL = "https://solidcore.co/auth/schedule"
    STUDIO_NAME = "Ballard"
    
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self._logged_in = False
        self._context: Optional[BrowserContext] = None
    
    async def _ensure_logged_in(self, page: Page) -> bool:
        """Log in if not already logged in."""
        if self._logged_in:
            return True
        
        try:
            logger.info("Logging into solidcore...")
            await page.goto(self.LOGIN_URL)
            await page.wait_for_load_state('networkidle')
            
            # Fill login form
            # Note: Selectors may need updating if solidcore changes their site
            email_input = page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
            password_input = page.locator('input[type="password"], input[name="password"]')
            
            await email_input.fill(self.email)
            await password_input.fill(self.password)
            
            # Submit
            submit_button = page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("Log In")')
            await submit_button.click()
            
            # Wait for navigation
            await page.wait_for_url("**/schedule**", timeout=15000)
            
            self._logged_in = True
            logger.info("Successfully logged into solidcore")
            return True
            
        except Exception as e:
            logger.error(f"solidcore login failed: {e}")
            return False
    
    async def get_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """
        Get solidcore schedule for a specific date.
        
        Note: This is a template - you'll need to inspect solidcore's actual
        DOM structure and update the selectors accordingly.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available")
            return self._get_fallback_schedule(target_date)
        
        classes = []
        
        try:
            context = await browser_manager.new_context()
            page = await context.new_page()
            
            # Log in
            if not await self._ensure_logged_in(page):
                return self._get_fallback_schedule(target_date)
            
            # Navigate to schedule
            await page.goto(self.SCHEDULE_URL)
            await page.wait_for_load_state('networkidle')
            
            # Wait for schedule to load
            await page.wait_for_timeout(3000)  # Give React time to render
            
            # TODO: Navigate to specific date if needed
            # This depends on solidcore's UI - might need to click date picker
            
            # TODO: Filter to Ballard location
            # Look for location filter/dropdown
            
            # Extract classes
            # IMPORTANT: These selectors are PLACEHOLDERS
            # You need to inspect solidcore.co/auth/schedule to find real selectors
            
            # Example approach:
            # class_cards = await page.query_selector_all('[data-testid="class-card"]')
            # or
            # class_cards = await page.query_selector_all('.schedule-class, .class-item')
            
            # For now, return fallback
            logger.warning("solidcore scraping not fully implemented - using fallback schedule")
            classes = self._get_fallback_schedule(target_date)
            
            await context.close()
            
        except Exception as e:
            logger.error(f"solidcore scraping failed: {e}")
            classes = self._get_fallback_schedule(target_date)
        
        return classes
    
    def _get_fallback_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """Return typical solidcore schedule when scraping fails."""
        weekday = target_date.weekday()
        date_str = target_date.strftime("%Y-%m-%d")
        
        # Typical solidcore schedule (50-minute classes)
        schedules = {
            0: ["06:00", "07:00", "09:00", "12:00", "17:30", "18:30", "19:30"],  # Monday
            1: ["06:00", "07:00", "09:00", "12:00", "17:30", "18:30"],  # Tuesday
            2: ["06:00", "07:00", "09:00", "12:00", "17:30", "18:30"],  # Wednesday
            3: ["06:00", "07:00", "09:00", "12:00", "17:30", "18:30"],  # Thursday
            4: ["06:00", "07:00", "09:00", "12:00", "17:00"],  # Friday
            5: ["08:00", "09:00", "10:00", "11:00"],  # Saturday
            6: ["08:00", "09:00", "10:00", "11:00"],  # Sunday
        }
        
        times = schedules.get(weekday, [])
        
        return [
            ScrapedClass(
                studio="solidcore",
                name="[solidcore]",
                time=time,
                date=date_str,
                duration_minutes=50,
                url=self.SCHEDULE_URL,
                is_bookable=self._is_bookable(target_date)
            )
            for time in times
        ]
    
    def _is_bookable(self, target_date: datetime) -> bool:
        """Check if date is within booking window (schedule drops on 23rd/25th)."""
        today = datetime.now()
        
        # If target is this month, it's bookable
        if target_date.month == today.month and target_date.year == today.year:
            return True
        
        # If target is next month and we're past the 23rd, it's bookable (for members)
        if target_date.month == (today.month % 12) + 1:
            return today.day >= 23
        
        return False


class CycleSanctuaryScraper:
    """
    Scraper for Cycle Sanctuary.
    
    Uses Mariana Tek widget - no authentication required to view schedule.
    """
    
    SCHEDULE_URL = "https://www.thecyclesanctuary.com/schedule"
    
    async def get_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """Get Cycle Sanctuary schedule for a specific date."""
        if not PLAYWRIGHT_AVAILABLE:
            return self._get_fallback_schedule(target_date)
        
        classes = []
        
        try:
            context = await browser_manager.new_context()
            page = await context.new_page()
            
            logger.info("Loading Cycle Sanctuary schedule...")
            await page.goto(self.SCHEDULE_URL)
            await page.wait_for_load_state('networkidle')
            
            # Wait for Mariana Tek widget to load
            await page.wait_for_timeout(5000)
            
            # The schedule is loaded via JavaScript/iframe
            # You'd need to inspect the actual page to find correct selectors
            
            # For now, use fallback
            logger.warning("Cycle Sanctuary scraping not fully implemented - using fallback")
            classes = self._get_fallback_schedule(target_date)
            
            await context.close()
            
        except Exception as e:
            logger.error(f"Cycle Sanctuary scraping failed: {e}")
            classes = self._get_fallback_schedule(target_date)
        
        return classes
    
    def _get_fallback_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """Return typical Cycle Sanctuary schedule."""
        weekday = target_date.weekday()
        date_str = target_date.strftime("%Y-%m-%d")
        
        schedules = {
            0: [  # Monday
                ("17:00", "Power Cycle 45", 45),
                ("18:00", "HIIT Cycle", 45),
            ],
            1: [  # Tuesday
                ("06:00", "Power Cycle 45", 45),
                ("09:00", "Performance Cycle 60", 60),
                ("17:30", "Power Cycle 45", 45),
                ("18:30", "HIIT Cycle", 45),
            ],
            2: [  # Wednesday
                ("06:00", "Power Cycle 45", 45),
                ("09:00", "Performance Cycle 60", 60),
                ("17:30", "Power Cycle 45", 45),
                ("18:30", "Strength/HIIT Cycle", 45),
            ],
            3: [  # Thursday
                ("06:00", "Power Cycle 45", 45),
                ("09:00", "Performance Cycle 60", 60),
                ("17:30", "Power Cycle 45", 45),
                ("18:30", "HIIT Cycle", 45),
            ],
            4: [  # Friday
                ("06:00", "Power Cycle 45", 45),
                ("09:00", "Performance Cycle 60", 60),
            ],
            5: [  # Saturday
                ("08:30", "Power Cycle 45", 45),
                ("09:30", "Performance Cycle 60", 60),
                ("10:45", "Pilates", 50),
            ],
            6: [  # Sunday
                ("08:30", "Power Cycle 45", 45),
                ("09:30", "Performance Cycle 60", 60),
                ("10:45", "Core & Stretch", 45),
            ],
        }
        
        day_schedule = schedules.get(weekday, [])
        
        return [
            ScrapedClass(
                studio="cycle",
                name=name,
                time=time,
                date=date_str,
                duration_minutes=duration,
                url=self.SCHEDULE_URL,
                is_bookable=self._is_bookable(target_date)
            )
            for time, name, duration in day_schedule
        ]
    
    def _is_bookable(self, target_date: datetime) -> bool:
        """Check if date is within booking window (1 week out)."""
        today = datetime.now().date()
        target = target_date.date() if hasattr(target_date, 'date') else target_date
        days_out = (target - today).days
        return 0 <= days_out <= 7


class BallardPoolScraper:
    """
    Scraper for Ballard Public Pool (Seattle Parks).
    
    Uses ActiveCommunities platform.
    """
    
    SCHEDULE_URL = "https://anc.apm.activecommunities.com/seattle/calendars?defaultCalendarId=6&locationId=26"
    
    async def get_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """Get pool schedule - primarily lap swim times."""
        # ActiveCommunities is complex to scrape
        # Using fallback for typical lap swim schedule
        return self._get_fallback_schedule(target_date)
    
    def _get_fallback_schedule(self, target_date: datetime) -> List[ScrapedClass]:
        """Return typical Ballard Pool lap swim schedule."""
        weekday = target_date.weekday()
        date_str = target_date.strftime("%Y-%m-%d")
        
        # Typical lap swim times (check Seattle Parks for current hours)
        schedules = {
            0: [("05:30", 90), ("12:00", 60), ("18:00", 90)],  # Monday
            1: [("05:30", 90), ("12:00", 60), ("18:00", 90)],  # Tuesday
            2: [("05:30", 90), ("12:00", 60), ("18:00", 90)],  # Wednesday
            3: [("05:30", 90), ("12:00", 60), ("18:00", 90)],  # Thursday
            4: [("05:30", 90), ("12:00", 60)],  # Friday
            5: [("08:00", 120)],  # Saturday
            6: [("08:00", 120)],  # Sunday
        }
        
        day_schedule = schedules.get(weekday, [])
        
        return [
            ScrapedClass(
                studio="pool",
                name="Lap Swim",
                time=time,
                date=date_str,
                duration_minutes=duration,
                url=self.SCHEDULE_URL
            )
            for time, duration in day_schedule
        ]


# Aggregator for all scrapers
class ScheduleAggregator:
    """Combines data from multiple scrapers."""
    
    def __init__(self):
        self.solidcore: Optional[SolidcoreScraper] = None
        self.cycle = CycleSanctuaryScraper()
        self.pool = BallardPoolScraper()
        
        # Initialize solidcore if credentials available
        solidcore_email = os.environ.get("SOLIDCORE_EMAIL")
        solidcore_password = os.environ.get("SOLIDCORE_PASSWORD")
        if solidcore_email and solidcore_password:
            self.solidcore = SolidcoreScraper(solidcore_email, solidcore_password)
    
    async def get_all_schedules(self, target_date: datetime) -> Dict[str, List[ScrapedClass]]:
        """Get schedules from all scrapers."""
        results = {}
        
        # Cycle Sanctuary
        results["cycle"] = await self.cycle.get_schedule(target_date)
        
        # Ballard Pool
        results["pool"] = await self.pool.get_schedule(target_date)
        
        # solidcore (if configured)
        if self.solidcore:
            results["solidcore"] = await self.solidcore.get_schedule(target_date)
        else:
            # Use fallback schedule
            results["solidcore"] = SolidcoreScraper("", "")._get_fallback_schedule(target_date)
        
        return results
    
    async def shutdown(self):
        """Clean up browser resources."""
        await browser_manager.stop()


# Factory function
def create_schedule_aggregator() -> ScheduleAggregator:
    """Create a schedule aggregator with configured scrapers."""
    return ScheduleAggregator()


# Test function
async def test_scrapers():
    """Test the scrapers."""
    logging.basicConfig(level=logging.INFO)
    
    aggregator = create_schedule_aggregator()
    
    try:
        today = datetime.now()
        print(f"Fetching schedules for {today.strftime('%A, %B %d, %Y')}...\n")
        
        schedules = await aggregator.get_all_schedules(today)
        
        for studio, classes in schedules.items():
            print(f"\n{studio.upper()} ({len(classes)} classes):")
            for cls in classes[:5]:
                print(f"  {cls.time} - {cls.name} ({cls.duration_minutes} min)")
    
    finally:
        await aggregator.shutdown()


if __name__ == "__main__":
    asyncio.run(test_scrapers())
