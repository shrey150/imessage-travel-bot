"""
Vrbo scraper using Stagehand Python SDK
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from pydantic import BaseModel, Field
from stagehand import Stagehand, StagehandConfig


class VrboListing(BaseModel):
    """Vrbo listing model"""
    name: str = Field(description="Property title/name")
    pricePerNight: Optional[float] = Field(None, description="Price per night")
    totalPrice: Optional[float] = Field(None, description="Total price")
    rating: Optional[float] = Field(None, description="Rating out of 5")
    reviewCount: Optional[int] = Field(None, description="Number of reviews")
    imageUrl: Optional[str] = Field(None, description="Main image")
    amenities: Optional[List[str]] = Field(None, description="Amenities list")
    bedrooms: Optional[int] = Field(None, description="Number of bedrooms")
    beds: Optional[int] = Field(None, description="Number of beds")
    url: str = Field(default="", description="Listing URL")


class VrboResponse(BaseModel):
    """Response containing list of Vrbo listings"""
    listings: List[VrboListing]


class ScraperResult(BaseModel):
    """Result from scraper"""
    success: bool
    source: Optional[str] = None
    data: Optional[VrboResponse] = None
    error: Optional[str] = None


async def scrape_vrbo(
    location: str,
    start_date: str,
    end_date: str,
    adults: int = 2
) -> dict:
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
        
        # Construct search URL for Vrbo
        from urllib.parse import quote
        search_url = f"https://www.vrbo.com/search?destination={quote(location)}&startDate={start_date}&endDate={end_date}&adults={adults}"
        
        print(f"Navigating to: {search_url}")
        
        # Use 'domcontentloaded' instead of 'networkidle'
        await page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
        print("✅ Page loaded (DOM ready)")
        
        print("⏳ Waiting for page to settle...")
        await page.wait_for_timeout(3000)
        
        # Handle common Vrbo popups/modals
        print("🔍 Checking for popups...")
        try:
            await page.act("Close any modal, popup, or cookie banner by clicking accept, close, or X button")
            await page.wait_for_timeout(1000)
            print("✅ Dismissed popups")
        except Exception as e:
            print("ℹ️  No popups found")
        
        print("⏳ Waiting for results to render...")
        await page.wait_for_timeout(2000)
        print("✅ Ready to extract")
        
        # Extract listings
        print("🤖 Extracting listings with AI...")
        listings_data = await page.extract(
            instruction="Extract all visible Vrbo rental listings. For each listing get: property name, price per night, total price, rating, number of reviews, bedrooms, beds, and amenities if visible.",
            schema=VrboResponse
        )
        
        print(f"✅ Extracted {len(listings_data.listings)} listings")
        
        # Post-process: Get real URLs from the page DOM
        print("🔗 Fetching real listing URLs from DOM...")
        real_urls = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="/vacation-rentals/"], a[href*="vrbo.com"]'));
                return links
                    .map(link => link.href)
                    .filter(href => href.includes('/vacation-rentals/') || href.includes('vrbo.com'))
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
            "source": "vrbo",
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
            "error": "Missing required arguments: location, startDate, endDate"
        }))
        sys.exit(1)
    
    location = sys.argv[1]
    start_date = sys.argv[2]
    end_date = sys.argv[3]
    adults = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    
    await scrape_vrbo(location, start_date, end_date, adults)


if __name__ == "__main__":
    asyncio.run(main())

