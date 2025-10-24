"""
Google Flights scraper using Stagehand Python SDK
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from pydantic import BaseModel, Field
from stagehand import Stagehand, StagehandConfig


class Flight(BaseModel):
    """Flight model"""
    airline: str = Field(description="Airline name")
    flightNumber: Optional[str] = Field(None, description="Flight number")
    departureTime: str = Field(description="Departure time")
    departureAirport: str = Field(description="Departure airport code")
    arrivalTime: str = Field(description="Arrival time")
    arrivalAirport: str = Field(description="Arrival airport code")
    duration: str = Field(description="Flight duration")
    stops: int = Field(description="Number of stops")
    price: float = Field(description="Price in dollars")
    url: Optional[str] = Field(None, description="Link to book")


class FlightsResponse(BaseModel):
    """Response containing list of flights"""
    flights: List[Flight]


class ScraperResult(BaseModel):
    """Result from scraper"""
    success: bool
    data: Optional[FlightsResponse] = None
    error: Optional[str] = None


async def scrape_google_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None
) -> dict:
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
    config = StagehandConfig(
        env="BROWSERBASE",
        verbose=1,
        enable_caching=True,
        api_key=os.getenv("BROWSERBASE_API_KEY"),
        project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
        model_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    stagehand = Stagehand(config)
    page = None
    
    try:
        await stagehand.init()
        page = stagehand.page
        
        # Navigate to Google Flights
        print("🌐 Navigating to Google Flights...")
        await page.goto("https://www.google.com/travel/flights", wait_until='domcontentloaded', timeout=60000)
        print("✅ Page loaded")
        
        print("⏳ Waiting for page to settle...")
        await page.wait_for_timeout(3000)
        
        # Handle cookie banners
        print("🔍 Checking for popups...")
        try:
            await page.act("Accept cookies if there's a cookie banner")
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        print("✅ Ready to fill form")
        
        # Fill origin airport
        print(f"📍 Entering origin: {origin}")
        await page.act(f"Click on the origin/departure airport field and clear it")
        await page.wait_for_timeout(500)
        await page.act(f'Type "{origin}" in the origin airport field')
        await page.wait_for_timeout(2000)
        await page.act("Press Enter or select the first airport suggestion")
        await page.wait_for_timeout(1000)
        print("✅ Origin set")
        
        # Fill destination airport
        print(f"📍 Entering destination: {destination}")
        await page.act(f"Click on the destination/arrival airport field and clear it")
        await page.wait_for_timeout(500)
        await page.act(f'Type "{destination}" in the destination airport field')
        await page.wait_for_timeout(2000)
        await page.act("Press Enter or select the first airport suggestion")
        await page.wait_for_timeout(1000)
        print("✅ Destination set")
        
        # Set departure date
        print(f"📅 Setting departure date: {departure_date}")
        await page.act("Click on the departure date field")
        await page.wait_for_timeout(1000)
        await page.act(f"Select the date {departure_date} from the calendar picker")
        await page.wait_for_timeout(1000)
        print("✅ Departure date set")
        
        # Set return date if provided
        if return_date:
            print(f"📅 Setting return date: {return_date}")
            await page.act(f"Select the date {return_date} from the calendar picker")
            await page.wait_for_timeout(1000)
            print("✅ Return date set")
        
        # Click search button
        print("🔍 Clicking search button...")
        await page.act("Click the blue Search button")
        await page.wait_for_timeout(2000)
        
        print("⏳ Waiting for flight results to load (this takes ~10-15 seconds)...")
        await page.wait_for_timeout(12000)
        print("✅ Results should be loaded")
        
        # Extract flight results
        print("🤖 Extracting flight data with AI...")
        flights_data = await page.extract(
            instruction="Extract flight options with airline, flight number, departure/arrival times and airports, duration, number of stops, and price",
            schema=FlightsResponse
        )
        
        print(f"✅ Extracted {len(flights_data.flights)} flights")
        
        # Print final result clearly
        print("\n" + "=" * 80)
        print("📊 FINAL RESULT:")
        print("=" * 80)
        result = {
            "success": True,
            "data": flights_data.model_dump()
        }
        print(json.dumps(result))
        print("=" * 80)
        
        return result
        
    except Exception as error:
        error_message = str(error)
        
        print("\n" + "=" * 80)
        print("❌ ERROR:")
        print("=" * 80)
        result = {
            "success": False,
            "error": error_message
        }
        print(json.dumps(result))
        print("=" * 80)
        
        return result
        
    finally:
        if page is not None:
            await stagehand.close()
            print("🧹 Browserbase session closed")


async def main():
    """Main execution when run as script"""
    if len(sys.argv) < 4:
        print(json.dumps({
            "success": False,
            "error": "Missing required arguments: origin, destination, departureDate"
        }))
        sys.exit(1)
    
    origin = sys.argv[1]
    destination = sys.argv[2]
    departure_date = sys.argv[3]
    return_date = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "null" else None
    
    await scrape_google_flights(origin, destination, departure_date, return_date)


if __name__ == "__main__":
    asyncio.run(main())

