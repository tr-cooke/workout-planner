"""
Mindbody API Integration for barre3 Ballard
============================================

Setup Instructions:
1. Go to https://developers.mindbodyonline.com/
2. Click "Get Started" and create a developer account
3. Create an app to get your API credentials
4. Find barre3 Ballard's Site ID (see instructions below)

Environment Variables Needed:
- MINDBODY_API_KEY: Your Mindbody API key
- MINDBODY_SITE_ID: The barre3 Ballard site ID (e.g., -99 for sandbox, real ID for production)
"""

import os
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class Barre3Class:
    """Represents a barre3 class."""
    class_id: int
    name: str
    start_time: datetime
    end_time: datetime
    instructor: str
    studio: str
    spots_available: int
    is_canceled: bool
    
    def to_dict(self) -> dict:
        return {
            "studio": "barre3",
            "class_id": self.class_id,
            "name": self.name,
            "time": self.start_time.strftime("%H:%M"),
            "date": self.start_time.strftime("%Y-%m-%d"),
            "instructor": self.instructor,
            "spots_available": self.spots_available,
            "duration_minutes": int((self.end_time - self.start_time).total_seconds() / 60),
            "is_canceled": self.is_canceled
        }


class MindbodyClient:
    """
    Client for Mindbody API.
    
    Documentation: https://developers.mindbodyonline.com/PublicDocumentation/V6
    """
    
    BASE_URL = "https://api.mindbodyonline.com/public/v6"
    
    def __init__(self, api_key: str, site_id: str):
        """
        Initialize the Mindbody client.
        
        Args:
            api_key: Your Mindbody API key (from developer portal)
            site_id: The studio's site ID (barre3 Ballard's ID)
        """
        self.api_key = api_key
        self.site_id = site_id
        self.session: Optional[aiohttp.ClientSession] = None
        self._user_token: Optional[str] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "SiteId": self.site_id,
        }
        if self._user_token:
            headers["Authorization"] = f"Bearer {self._user_token}"
        return headers
    
    async def get_classes(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        class_description_ids: Optional[List[int]] = None,
        staff_ids: Optional[List[int]] = None,
        location_ids: Optional[List[int]] = None,
    ) -> List[Barre3Class]:
        """
        Get classes within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range (defaults to start_date + 7 days)
            class_description_ids: Filter by specific class types
            staff_ids: Filter by specific instructors
            location_ids: Filter by specific locations
            
        Returns:
            List of Barre3Class objects
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        if end_date is None:
            end_date = start_date + timedelta(days=7)
        
        params = {
            "StartDateTime": start_date.isoformat(),
            "EndDateTime": end_date.isoformat(),
        }
        
        if class_description_ids:
            params["ClassDescriptionIds"] = ",".join(map(str, class_description_ids))
        if staff_ids:
            params["StaffIds"] = ",".join(map(str, staff_ids))
        if location_ids:
            params["LocationIds"] = ",".join(map(str, location_ids))
        
        try:
            async with self.session.get(
                f"{self.BASE_URL}/class/classes",
                headers=self._get_headers(),
                params=params
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_classes(data.get("Classes", []))
                else:
                    error_text = await response.text()
                    logger.error(f"Mindbody API error: {response.status} - {error_text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching classes: {e}")
            return []
    
    def _parse_classes(self, classes_data: List[dict]) -> List[Barre3Class]:
        """Parse API response into Barre3Class objects."""
        classes = []
        for cls in classes_data:
            try:
                classes.append(Barre3Class(
                    class_id=cls.get("Id", 0),
                    name=cls.get("ClassDescription", {}).get("Name", "barre3"),
                    start_time=datetime.fromisoformat(cls["StartDateTime"].replace("Z", "+00:00")),
                    end_time=datetime.fromisoformat(cls["EndDateTime"].replace("Z", "+00:00")),
                    instructor=cls.get("Staff", {}).get("Name", "TBD"),
                    studio=cls.get("Location", {}).get("Name", "barre3 Ballard"),
                    spots_available=cls.get("MaxCapacity", 0) - cls.get("TotalBooked", 0),
                    is_canceled=cls.get("IsCanceled", False)
                ))
            except Exception as e:
                logger.warning(f"Error parsing class: {e}")
                continue
        return classes
    
    async def get_locations(self) -> List[dict]:
        """Get all locations for the site."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            async with self.session.get(
                f"{self.BASE_URL}/site/locations",
                headers=self._get_headers()
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("Locations", [])
                return []
        except Exception as e:
            logger.error(f"Error fetching locations: {e}")
            return []
    
    async def get_staff(self) -> List[dict]:
        """Get all staff/instructors for the site."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            async with self.session.get(
                f"{self.BASE_URL}/staff/staff",
                headers=self._get_headers()
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("StaffMembers", [])
                return []
        except Exception as e:
            logger.error(f"Error fetching staff: {e}")
            return []


async def find_barre3_site_id():
    """
    Helper to find barre3 Ballard's site ID.
    
    Note: You may need to contact Mindbody or search their directory
    to find the exact site ID for barre3 Ballard.
    
    Common approaches:
    1. Check the barre3 booking URL for clues
    2. Use Mindbody's site search API (if available)
    3. Contact barre3 directly and ask for their Mindbody site ID
    """
    print("""
    To find barre3 Ballard's Mindbody Site ID:
    
    1. Go to: https://clients.mindbodyonline.com/classic/ws?studioid=XXXXX
       (The XXXXX is the site ID)
    
    2. Or check the booking widget URL on barre3's website
    
    3. Or contact barre3 Ballard directly and ask for their 
       "Mindbody Site ID" for API integration
    
    Common barre3 site IDs often start with higher numbers (e.g., 5-6 digits)
    """)


# Factory function
def create_barre3_client() -> Optional[MindbodyClient]:
    """Create a Mindbody client for barre3 if credentials are available."""
    api_key = os.environ.get("MINDBODY_API_KEY")
    site_id = os.environ.get("MINDBODY_SITE_ID")
    
    if not api_key or not site_id:
        logger.warning("Mindbody credentials not configured")
        return None
    
    return MindbodyClient(api_key, site_id)


# Test function
async def test_mindbody():
    """Test the Mindbody integration."""
    client = create_barre3_client()
    
    if not client:
        print("Set MINDBODY_API_KEY and MINDBODY_SITE_ID environment variables")
        return
    
    async with client:
        print("Fetching barre3 classes...")
        classes = await client.get_classes(datetime.now())
        
        print(f"\nFound {len(classes)} classes:\n")
        for cls in classes[:5]:
            print(f"  {cls.start_time.strftime('%a %m/%d %I:%M %p')} - {cls.name} with {cls.instructor}")
            print(f"    Spots available: {cls.spots_available}")


if __name__ == "__main__":
    asyncio.run(test_mindbody())
