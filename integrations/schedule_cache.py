"""
Schedule Cache
==============

Caches scraped schedule data and refreshes weekly.
Stores data in a JSON file to persist across restarts.

Usage:
    from integrations.schedule_cache import ScheduleCache
    
    cache = ScheduleCache()
    
    # Get solidcore classes (scrapes if cache is stale)
    classes = await cache.get_solidcore_schedule()
    
    # Force refresh
    classes = await cache.get_solidcore_schedule(force_refresh=True)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
import pytz

logger = logging.getLogger(__name__)

SEATTLE_TZ = pytz.timezone("America/Los_Angeles")

# Cache file location
CACHE_FILE = os.environ.get("SCHEDULE_CACHE_FILE", "/app/data/schedule_cache.json")

# How often to refresh each studio's schedule
REFRESH_INTERVALS = {
    "solidcore": timedelta(days=7),      # Weekly - schedule set monthly
    "cycle": timedelta(days=7),          # Weekly
    "barre3": timedelta(days=7),         # Weekly
    "pool": timedelta(days=7),           # Weekly
    "greenlake": timedelta(days=7),      # Weekly - consistent schedule
}


class ScheduleCache:
    """Manages cached schedule data with weekly refresh."""
    
    def __init__(self, cache_file: str = CACHE_FILE):
        self.cache_file = cache_file
        self.cache = self._load_cache()
    
    def _load_cache(self) -> dict:
        """Load cache from file."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading schedule cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save cache to file."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.debug("Schedule cache saved")
        except Exception as e:
            logger.error(f"Error saving schedule cache: {e}")
    
    def _is_stale(self, studio: str) -> bool:
        """Check if cached data for a studio is stale."""
        if studio not in self.cache:
            return True
        
        last_updated = self.cache[studio].get("last_updated")
        if not last_updated:
            return True
        
        try:
            last_dt = datetime.fromisoformat(last_updated)
            refresh_interval = REFRESH_INTERVALS.get(studio, timedelta(days=7))
            return datetime.now() - last_dt > refresh_interval
        except:
            return True
    
    def _get_cached_classes(self, studio: str) -> List[Dict]:
        """Get cached classes for a studio."""
        if studio in self.cache:
            return self.cache[studio].get("classes", [])
        return []
    
    def _update_cache(self, studio: str, classes: List[Dict]):
        """Update cache with new class data."""
        self.cache[studio] = {
            "last_updated": datetime.now().isoformat(),
            "classes": classes
        }
        self._save_cache()
    
    def get_cache_status(self) -> Dict[str, dict]:
        """Get status of all cached studios."""
        status = {}
        for studio in ["solidcore", "cycle", "barre3", "pool", "greenlake"]:
            if studio in self.cache:
                last_updated = self.cache[studio].get("last_updated", "Never")
                class_count = len(self.cache[studio].get("classes", []))
                is_stale = self._is_stale(studio)
                status[studio] = {
                    "last_updated": last_updated,
                    "class_count": class_count,
                    "is_stale": is_stale
                }
            else:
                status[studio] = {
                    "last_updated": "Never",
                    "class_count": 0,
                    "is_stale": True
                }
        return status
    
    async def get_solidcore_schedule(self, force_refresh: bool = False) -> List[Dict]:
        """Get solidcore schedule, scraping if cache is stale."""
        studio = "solidcore"
        
        if not force_refresh and not self._is_stale(studio):
            logger.info(f"Using cached {studio} schedule")
            return self._get_cached_classes(studio)
        
        logger.info(f"Refreshing {studio} schedule...")
        
        try:
            from integrations.solidcore_scraper import scrape_solidcore_schedule, get_fallback_schedule
            
            classes = await scrape_solidcore_schedule(days_ahead=14)
            
            if classes:
                class_dicts = [c.to_dict() for c in classes]
                self._update_cache(studio, class_dicts)
                return class_dicts
            else:
                # Use fallback
                logger.warning(f"Scraping failed, using fallback for {studio}")
                fallback_classes = []
                today = datetime.now(SEATTLE_TZ)
                for i in range(14):
                    date = today + timedelta(days=i)
                    fallback_classes.extend(get_fallback_schedule(date))
                self._update_cache(studio, fallback_classes)
                return fallback_classes
                
        except ImportError:
            logger.error("Solidcore scraper not available")
            return self._get_cached_classes(studio)
        except Exception as e:
            logger.error(f"Error refreshing {studio}: {e}")
            return self._get_cached_classes(studio)
    
    async def get_cycle_schedule(self, force_refresh: bool = False) -> List[Dict]:
        """Get Cycle Sanctuary schedule, scraping if cache is stale."""
        studio = "cycle"
        
        if not force_refresh and not self._is_stale(studio):
            logger.info(f"Using cached {studio} schedule")
            return self._get_cached_classes(studio)
        
        logger.info(f"Refreshing {studio} schedule...")
        
        try:
            from integrations.cycle_scraper import scrape_cycle_schedule, get_cycle_fallback_schedule
            
            classes = await scrape_cycle_schedule(days_ahead=7)
            
            if classes:
                class_dicts = [c.to_dict() for c in classes]
                self._update_cache(studio, class_dicts)
                return class_dicts
            else:
                # Use fallback
                logger.warning(f"Scraping failed, using fallback for {studio}")
                fallback_classes = []
                today = datetime.now(SEATTLE_TZ)
                for i in range(7):
                    date = today + timedelta(days=i)
                    fallback_classes.extend(get_cycle_fallback_schedule(date))
                self._update_cache(studio, fallback_classes)
                return fallback_classes
                
        except ImportError:
            logger.error("Cycle scraper not available")
            return self._get_cached_classes(studio)
        except Exception as e:
            logger.error(f"Error refreshing {studio}: {e}")
            return self._get_cached_classes(studio)
    
    async def get_barre3_schedule(self, force_refresh: bool = False) -> List[Dict]:
        """Get barre3 schedule (via scraping)."""
        studio = "barre3"
        
        if not force_refresh and not self._is_stale(studio):
            logger.info(f"Using cached {studio} schedule")
            return self._get_cached_classes(studio)
        
        logger.info(f"Refreshing {studio} schedule...")
        
        try:
            from integrations.barre3_scraper import scrape_barre3_schedule, get_barre3_fallback_schedule
            
            classes = await scrape_barre3_schedule(days_ahead=14)
            
            if classes:
                class_dicts = [c.to_dict() for c in classes]
                self._update_cache(studio, class_dicts)
                return class_dicts
            else:
                # Use fallback
                logger.warning(f"Scraping failed, using fallback for {studio}")
                fallback_classes = []
                today = datetime.now(SEATTLE_TZ)
                for i in range(14):
                    date = today + timedelta(days=i)
                    fallback_classes.extend(get_barre3_fallback_schedule(date))
                self._update_cache(studio, fallback_classes)
                return fallback_classes
                
        except ImportError:
            logger.error("barre3 scraper not available, using built-in fallback")
            fallback_classes = self._get_barre3_fallback()
            self._update_cache(studio, fallback_classes)
            return fallback_classes
        except Exception as e:
            logger.error(f"Error refreshing {studio}: {e}")
            cached = self._get_cached_classes(studio)
            if cached:
                return cached
            return self._get_barre3_fallback()
    
    def _get_barre3_fallback(self) -> List[Dict]:
        """Get fallback barre3 schedule."""
        fallback = {
            0: [("06:00", "barre3 Signature", 60), ("09:30", "barre3 Signature", 60), 
                ("12:00", "barre3 Express 30", 30), ("17:45", "barre3 Signature", 60)],
            1: [("06:00", "barre3 Signature", 60), ("09:30", "barre3 Cardio 45", 45),
                ("12:00", "barre3 Signature", 60), ("17:45", "barre3 Signature", 60)],
            2: [("06:00", "barre3 Signature", 60), ("09:30", "barre3 Signature", 60),
                ("12:00", "barre3 Express 30", 30), ("17:45", "barre3 Cardio 45", 45)],
            3: [("06:00", "barre3 Signature", 60), ("09:30", "barre3 Signature", 60),
                ("12:00", "barre3 Signature", 60), ("17:45", "barre3 Signature", 60)],
            4: [("06:00", "barre3 Signature", 60), ("09:30", "barre3 Cardio 45", 45),
                ("12:00", "barre3 Express 30", 30), ("17:00", "barre3 Signature", 60)],
            5: [("08:00", "barre3 Signature", 60), ("09:15", "barre3 Cardio 45", 45),
                ("10:30", "barre3 Signature", 60)],
            6: [("09:00", "barre3 Signature", 60), ("10:15", "barre3 Signature", 60)],
        }
        
        classes = []
        today = datetime.now(SEATTLE_TZ)
        for i in range(14):
            date = today + timedelta(days=i)
            weekday = date.weekday()
            date_str = date.strftime("%Y-%m-%d")
            
            for time, name, duration in fallback.get(weekday, []):
                classes.append({
                    "studio": "barre3",
                    "class_name": name,
                    "name": name,
                    "time": time,
                    "date": date_str,
                    "instructor": "TBD",
                    "duration_minutes": duration
                })
        
        return classes
    
    async def get_pool_schedule(self, force_refresh: bool = False) -> List[Dict]:
        """Get Ballard Pool lap swim schedule."""
        studio = "pool"
        
        if not force_refresh and not self._is_stale(studio):
            logger.info(f"Using cached {studio} schedule")
            return self._get_cached_classes(studio)
        
        logger.info(f"Refreshing {studio} schedule...")
        
        try:
            from integrations.pool_scraper import scrape_pool_schedule, get_pool_classes_for_date, get_fallback_pool_schedule, FALLBACK_SESSIONS
            
            sessions = await scrape_pool_schedule()
            
            if sessions:
                # Convert sessions to classes for the next 14 days
                all_classes = []
                today = datetime.now(SEATTLE_TZ)
                for i in range(14):
                    date = today + timedelta(days=i)
                    day_classes = get_pool_classes_for_date(sessions, date)
                    all_classes.extend(day_classes)
                
                self._update_cache(studio, all_classes)
                return all_classes
            else:
                # Use fallback
                logger.warning(f"Scraping failed, using fallback for {studio}")
                fallback_classes = []
                today = datetime.now(SEATTLE_TZ)
                for i in range(14):
                    date = today + timedelta(days=i)
                    fallback_classes.extend(get_fallback_pool_schedule(date))
                self._update_cache(studio, fallback_classes)
                return fallback_classes
                
        except ImportError:
            logger.error("Pool scraper not available, using built-in fallback")
            return self._get_pool_fallback()
        except Exception as e:
            logger.error(f"Error refreshing {studio}: {e}")
            cached = self._get_cached_classes(studio)
            if cached:
                return cached
            return self._get_pool_fallback()
    
    def _get_pool_fallback(self) -> List[Dict]:
        """Get fallback Ballard Pool lap swim schedule."""
        # Typical lap swim times at Ballard Pool
        fallback = {
            0: [("05:30", "Lap Swim", 90), ("11:30", "Lap Swim", 90), ("18:00", "Lap Swim", 90)],
            1: [("05:30", "Lap Swim", 90), ("11:30", "Lap Swim", 90), ("18:00", "Lap Swim", 90)],
            2: [("05:30", "Lap Swim", 90), ("11:30", "Lap Swim", 90), ("18:00", "Lap Swim", 90)],
            3: [("05:30", "Lap Swim", 90), ("11:30", "Lap Swim", 90), ("18:00", "Lap Swim", 90)],
            4: [("05:30", "Lap Swim", 90), ("11:30", "Lap Swim", 90), ("18:00", "Lap Swim", 90)],
            5: [("08:00", "Lap Swim", 120), ("12:00", "Lap Swim", 120)],
            6: [("08:00", "Lap Swim", 120), ("12:00", "Lap Swim", 120)],
        }
        
        classes = []
        today = datetime.now(SEATTLE_TZ)
        for i in range(14):
            date = today + timedelta(days=i)
            weekday = date.weekday()
            date_str = date.strftime("%Y-%m-%d")
            
            for time, name, duration in fallback.get(weekday, []):
                classes.append({
                    "studio": "pool",
                    "class_name": name,
                    "name": name,
                    "time": time,
                    "date": date_str,
                    "instructor": "",
                    "duration_minutes": duration
                })
        
        return classes
    
    async def get_all_schedules(self, force_refresh: bool = False) -> Dict[str, List[Dict]]:
        """Get all studio schedules."""
        return {
            "solidcore": await self.get_solidcore_schedule(force_refresh),
            "cycle": await self.get_cycle_schedule(force_refresh),
            "barre3": await self.get_barre3_schedule(force_refresh),
            "pool": await self.get_pool_schedule(force_refresh),
        }
    
    def get_classes_for_date(self, studio: str, target_date: datetime) -> List[Dict]:
        """Get cached classes for a specific studio and date."""
        target_str = target_date.strftime("%Y-%m-%d")
        classes = self._get_cached_classes(studio)
        return [c for c in classes if c.get("date") == target_str]
    
    async def refresh_all(self):
        """Force refresh all schedules (useful for weekly cron job)."""
        logger.info("Refreshing all schedules...")
        await self.get_all_schedules(force_refresh=True)
        logger.info("All schedules refreshed!")


# Singleton instance
_cache_instance = None

def get_schedule_cache() -> ScheduleCache:
    """Get the singleton schedule cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ScheduleCache()
    return _cache_instance


# Test function
async def test_cache():
    """Test the schedule cache."""
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Schedule Cache...")
    print("=" * 50)
    
    cache = get_schedule_cache()
    
    # Show cache status
    print("\nCache Status:")
    for studio, status in cache.get_cache_status().items():
        stale = "⚠️ STALE" if status["is_stale"] else "✅"
        print(f"  {studio}: {status['class_count']} classes, last updated: {status['last_updated']} {stale}")
    
    # Test getting schedules
    print("\nFetching schedules...")
    
    solidcore = await cache.get_solidcore_schedule()
    print(f"  solidcore: {len(solidcore)} classes")
    
    cycle = await cache.get_cycle_schedule()
    print(f"  cycle: {len(cycle)} classes")
    
    barre3 = await cache.get_barre3_schedule()
    print(f"  barre3: {len(barre3)} classes")
    
    pool = await cache.get_pool_schedule()
    print(f"  pool: {len(pool)} classes")
    
    # Show updated cache status
    print("\nUpdated Cache Status:")
    for studio, status in cache.get_cache_status().items():
        stale = "⚠️ STALE" if status["is_stale"] else "✅"
        print(f"  {studio}: {status['class_count']} classes {stale}")


if __name__ == "__main__":
    asyncio.run(test_cache())