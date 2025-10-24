"""
Airbnb scraper using Stagehand Python SDK
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from pydantic import BaseModel, Field
from stagehand import Stagehand, StagehandConfig


class Listing(BaseModel):
    """Airbnb listing model"""
    name: str = Field(description="Listing title/name")
    pricePerNight: Optional[float] = Field(None, description="Price per night in dollars")
    totalPrice: Optional[float] = Field(None, description="Total price for the stay in dollars")
    rating: Optional[float] = Field(None, description="Average rating out of 5")
    reviewCount: Optional[int] = Field(None, description="Number of reviews")
    imageUrl: Optional[str] = Field(None, description="Main image URL")
    amenities: Optional[List[str]] = Field(None, description="List of amenities")
    bedrooms: Optional[int] = Field(None, description="Number of bedrooms")
    beds: Optional[int] = Field(None, description="Number of beds")
    url: str = Field(default="", description="Listing URL")


class ListingsResponse(BaseModel):
    """Response containing list of listings"""
    listings: List[Listing]


class ScraperResult(BaseModel):
    """Result from scraper"""
    success: bool
    source: Optional[str] = None
    data: Optional[ListingsResponse] = None
    error: Optional[str] = None


async def scrape_airbnb(
    location: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None
) -> dict:
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
    config = StagehandConfig(
        env="BROWSERBASE",
        verbose=2,
        enable_caching=True,
        api_key=os.getenv("BROWSERBASE_API_KEY"),
        project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
        model_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    stagehand = Stagehand(config)
    page = None
    
    try:
        print("🚀 Initializing Stagehand...")
        await stagehand.init()
        page = stagehand.page
        print("✅ Stagehand initialized")
        
        # Construct search URL
        from urllib.parse import quote
        search_url = f"https://www.airbnb.com/s/{quote(location)}/homes?checkin={checkin}&checkout={checkout}&adults={adults}"
        
        if min_price and max_price:
            full_url = f"{search_url}&price_min={min_price}&price_max={max_price}"
        else:
            full_url = search_url
        
        print(f"🌐 Navigating to: {full_url}")
        
        # Use 'domcontentloaded' instead of 'networkidle'
        await page.goto(full_url, wait_until='domcontentloaded', timeout=60000)
        print("✅ Page loaded (DOM ready)")
        
        print("⏳ Waiting for page to settle...")
        await page.wait_for_timeout(3000)
        
        # Handle common Airbnb popups/modals
        print("🔍 Checking for popups/modals...")
        try:
            await page.act("Click the 'Got it' button if it exists")
            await page.wait_for_timeout(1000)
            print("✅ Dismissed popup")
        except Exception as e:
            print("ℹ️  No popup found or already dismissed")
        
        # Try to close any other modals
        try:
            await page.act("Close any modal or popup by clicking the X button if it exists")
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        print("⏳ Waiting for results to fully render...")
        await page.wait_for_timeout(2000)
        print("✅ Ready to extract")
        
        # Extract listings using Stagehand
        print("🤖 Extracting listings with AI...")
        listings_data = await page.extract(
            instruction="Extract all visible Airbnb listings. For each listing, get: property name, price per night in dollars, total price for the stay in dollars, rating (out of 5), number of reviews, bedrooms, and beds. Get as many listings as you can see on the page.",
            schema=ListingsResponse
        )
        
        print(f"✅ Extracted {len(listings_data.listings)} listings")
        
        # Post-process: Get real URLs from the page DOM
        print("🔗 Fetching real listing URLs from DOM...")
        real_urls = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="/rooms/"]'));
                return links
                    .map(link => link.href)
                    .filter((href, idx, arr) => arr.indexOf(href) === idx)
                    .slice(0, 20);
            }
        """)
        
        print(f"✅ Found {len(real_urls)} unique listing URLs")
        
        # Match extracted listings with real URLs
        for i in range(min(len(listings_data.listings), len(real_urls))):
            listings_data.listings[i].url = real_urls[i]
        
        # Print final result clearly
        print("\n" + "=" * 80)
        print("📊 FINAL RESULT:")
        print("=" * 80)
        result = {
            "success": True,
            "source": "airbnb",
            "data": listings_data.model_dump()
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
            "error": "Missing required arguments: location, checkin, checkout"
        }))
        sys.exit(1)
    
    location = sys.argv[1]
    checkin = sys.argv[2]
    checkout = sys.argv[3]
    adults = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    min_price = int(sys.argv[5]) if len(sys.argv) > 5 else None
    max_price = int(sys.argv[6]) if len(sys.argv) > 6 else None
    
    await scrape_airbnb(location, checkin, checkout, adults, min_price, max_price)


if __name__ == "__main__":
    asyncio.run(main())

