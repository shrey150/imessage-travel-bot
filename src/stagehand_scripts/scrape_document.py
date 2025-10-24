"""
Generic document/webpage scraper using Stagehand Python SDK
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from pydantic import BaseModel, Field
from stagehand import Stagehand, StagehandConfig


class AccessCode(BaseModel):
    """Access code model"""
    name: str = Field(description="What the code is for (garage, lockbox, front door, etc.)")
    code: str = Field(description="The actual code/PIN")


class VenueLogistics(BaseModel):
    """Venue logistics data model"""
    address: Optional[str] = Field(None, description="Full address")
    checkInTime: Optional[str] = Field(None, description="Check-in time")
    checkOutTime: Optional[str] = Field(None, description="Check-out time")
    wifiNetwork: Optional[str] = Field(None, description="WiFi network name")
    wifiPassword: Optional[str] = Field(None, description="WiFi password")
    phoneNumber: Optional[str] = Field(None, description="Contact phone number")
    accessCodes: Optional[List[AccessCode]] = Field(None, description="Access codes for doors, garages, lockboxes, etc.")
    hostName: Optional[str] = Field(None, description="Host or property manager name")
    parkingInfo: Optional[str] = Field(None, description="Parking instructions")
    quietHours: Optional[str] = Field(None, description="Quiet hours or noise policy")
    houseRules: Optional[str] = Field(None, description="Key house rules or restrictions")


class DocumentData(BaseModel):
    """Document data model"""
    fullText: str
    textChunks: List[str]
    structuredData: VenueLogistics
    title: str
    documentType: str


class ScraperResult(BaseModel):
    """Result from scraper"""
    success: bool
    data: Optional[DocumentData] = None
    error: Optional[str] = None


async def scrape_document(url: str) -> dict:
    """
    Scrape any document/webpage for logistics info
    
    Args:
        url: URL to scrape (Airbnb, Google Doc, any HTML page)
    
    Returns:
        Dict with success, fullText, textChunks, structuredData, title, documentType
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
        
        print(f"🌐 Navigating to: {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        print("✅ Page loaded")
        
        print("⏳ Waiting for page to settle...")
        await page.wait_for_timeout(3000)
        
        # Handle popups and interstitials
        print("🔍 Checking for popups and interstitials...")
        
        # Handle Google Docs app download prompt
        if "docs.google.com" in url:
            try:
                print("📱 Detected Google Doc - checking for app prompt...")
                await page.act("Click 'No, I'm not interested' or dismiss any app download prompt")
                await page.wait_for_timeout(2000)
                print("✅ Dismissed Google Docs app prompt")
            except Exception as e:
                print("ℹ️  No app prompt found or already dismissed")
        
        # Handle general popups
        try:
            await page.act("Close any modal, popup, or accept cookies if present")
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Handle Airbnb "Got it" button
        if "airbnb.com" in url:
            try:
                await page.act("Click the 'Got it' button if it exists")
                await page.wait_for_timeout(1000)
            except Exception:
                pass
        
        print("✅ Ready to extract")
        
        # Get page title
        title = await page.evaluate("() => document.title")
        
        # Determine document type
        document_type = "html"
        if "airbnb.com" in url:
            document_type = "airbnb"
        elif "vrbo.com" in url:
            document_type = "vrbo"
        elif "docs.google.com" in url:
            document_type = "google_doc"
        
        # Extract all text content
        print("📄 Extracting full text content...")
        full_text = await page.evaluate("() => document.body.innerText")
        print(f"✅ Extracted {len(full_text)} characters of text")
        
        # Split into chunks for better indexing
        text_chunks = []
        chunk_size = 1000
        for i in range(0, len(full_text), chunk_size):
            text_chunks.append(full_text[i:i + chunk_size])
        print(f"✅ Split into {len(text_chunks)} chunks")
        
        # Extract structured logistics data with AI
        print("🤖 Extracting structured logistics data with AI...")
        structured_data = await page.extract(
            instruction="Extract important logistics information from this page including: address, check-in/out times, WiFi details, contact phone, access codes (garage, lockbox, doors, etc.), host name, parking info, quiet hours, and house rules. If information is not present, that's okay.",
            schema=VenueLogistics
        )
        
        print("✅ Extracted structured data")
        
        # Print final result
        print("\n" + "=" * 80)
        print("📊 FINAL RESULT:")
        print("=" * 80)
        result = {
            "success": True,
            "data": {
                "fullText": full_text[:500] + "...",  # Truncate for output
                "textChunks": [c[:100] + "..." for c in text_chunks],  # Truncate
                "structuredData": structured_data.model_dump() if hasattr(structured_data, 'model_dump') else structured_data,
                "title": title,
                "documentType": document_type
            }
        }
        print(json.dumps(result))
        print("=" * 80)
        
        # Return full data (not truncated)
        return {
            "success": True,
            "data": {
                "fullText": full_text,
                "textChunks": text_chunks,
                "structuredData": structured_data.model_dump() if hasattr(structured_data, 'model_dump') else structured_data,
                "title": title,
                "documentType": document_type
            }
        }
        
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
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "Missing URL argument"
        }))
        sys.exit(1)
    
    url = sys.argv[1]
    await scrape_document(url)


if __name__ == "__main__":
    asyncio.run(main())

