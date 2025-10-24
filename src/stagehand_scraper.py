"""
Stagehand scraper infrastructure for web automation

Uses Stagehand Python SDK to scrape Airbnb, Vrbo, Google Flights, and airline check-in pages.
"""

import asyncio
import json
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path

from config import OPENAI_API_KEY, STAGEHAND_ENV, STAGEHAND_TIMEOUT

# Import all stagehand scripts
from stagehand_scripts import (
    scrape_airbnb,
    scrape_vrbo,
    scrape_google_flights,
    scrape_document,
)


class StagehandScraper:
    """Base class for Stagehand web scraping using Python SDK"""
    
    def __init__(self):
        self.openai_api_key = OPENAI_API_KEY
        self.env = STAGEHAND_ENV
        self.timeout = STAGEHAND_TIMEOUT
    
    async def scrape_airbnb(
        self,
        location: str,
        checkin: str,
        checkout: str,
        adults: int = 2,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None
    ) -> Dict:
        """
        Scrape Airbnb for listings
        
        Args:
            location: Destination (e.g., "Lake Tahoe, CA")
            checkin: Check-in date (YYYY-MM-DD)
            checkout: Check-out date (YYYY-MM-DD)
            adults: Number of adults
            min_price: Minimum price per night
            max_price: Maximum price per night
        
        Returns:
            Dict with success status and listings data
        """
        return await scrape_airbnb.scrape_airbnb(
            location, checkin, checkout, adults, min_price, max_price
        )
    
    async def scrape_vrbo(
        self,
        location: str,
        start_date: str,
        end_date: str,
        adults: int = 2
    ) -> Dict:
        """
        Scrape Vrbo for listings
        
        Args:
            location: Destination
            start_date: Check-in date (YYYY-MM-DD)
            end_date: Check-out date (YYYY-MM-DD)
            adults: Number of adults
        
        Returns:
            Dict with success status and listings data
        """
        return await scrape_vrbo.scrape_vrbo(location, start_date, end_date, adults)
    
    async def scrape_google_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None
    ) -> Dict:
        """
        Scrape Google Flights for flight options
        
        Args:
            origin: Origin airport code or city
            destination: Destination airport code or city
            departure_date: Departure date (YYYY-MM-DD)
            return_date: Return date (YYYY-MM-DD) for round trip
        
        Returns:
            Dict with success status and flights data
        """
        return await scrape_google_flights.scrape_google_flights(
            origin, destination, departure_date, return_date
        )
    
    async def scrape_document(self, url: str) -> Dict:
        """
        Scrape any document/webpage for logistics info
        
        Args:
            url: URL to scrape (Airbnb, Google Doc, any HTML page)
        
        Returns:
            Dict with success, fullText, textChunks, structuredData, title, documentType
        """
        return await scrape_document.scrape_document(url)
    
    async def search_venues_parallel(
        self,
        location: str,
        checkin: str,
        checkout: str,
        adults: int = 2,
        budget: Optional[int] = None
    ) -> List[Dict]:
        """
        Search both Airbnb and Vrbo in parallel
        
        Returns:
            Combined list of venue results
        """
        print(f"🔄 search_venues_parallel called with: {location}, {checkin}, {checkout}, {adults}, budget={budget}")
        
        min_price = None
        max_price = budget if budget else None
        
        # Run both scrapers in parallel
        print("🚀 Starting Airbnb and Vrbo scrapers in parallel...")
        airbnb_task = self.scrape_airbnb(location, checkin, checkout, adults, min_price, max_price)
        vrbo_task = self.scrape_vrbo(location, checkin, checkout, adults)
        
        airbnb_result, vrbo_result = await asyncio.gather(airbnb_task, vrbo_task, return_exceptions=True)
        
        print(f"📊 Airbnb result: {type(airbnb_result)}, success: {airbnb_result.get('success') if isinstance(airbnb_result, dict) else 'N/A'}")
        print(f"📊 Vrbo result: {type(vrbo_result)}, success: {vrbo_result.get('success') if isinstance(vrbo_result, dict) else 'N/A'}")
        
        venues = []
        
        # Process Airbnb results
        if isinstance(airbnb_result, dict) and airbnb_result.get("success"):
            listings = airbnb_result.get("data", {}).get("listings", [])
            print(f"✅ Airbnb: {len(listings)} listings")
            for listing in listings:
                listing['source'] = 'airbnb'
                venues.append(listing)
        elif isinstance(airbnb_result, Exception):
            print(f"❌ Airbnb exception: {airbnb_result}")
        else:
            print(f"❌ Airbnb failed: {airbnb_result.get('error') if isinstance(airbnb_result, dict) else 'Unknown'}")
        
        # Process Vrbo results
        if isinstance(vrbo_result, dict) and vrbo_result.get("success"):
            listings = vrbo_result.get("data", {}).get("listings", [])
            print(f"✅ Vrbo: {len(listings)} listings")
            for listing in listings:
                listing['source'] = 'vrbo'
                venues.append(listing)
        elif isinstance(vrbo_result, Exception):
            print(f"❌ Vrbo exception: {vrbo_result}")
        else:
            print(f"❌ Vrbo failed: {vrbo_result.get('error') if isinstance(vrbo_result, dict) else 'Unknown'}")
        
        print(f"📋 Total venues collected: {len(venues)}")
        return venues


# Global scraper instance
scraper = StagehandScraper()
