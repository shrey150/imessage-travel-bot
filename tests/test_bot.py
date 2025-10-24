"""
Test script for Travel Planner Bot

Tests the core functionality without needing a full iMessage connection.
"""

import asyncio
from src.stagehand_scraper import scraper
from models import TravelState, Member, FlightCriteria
from openai_helpers import extract_venue_criteria, extract_flight_criteria
import json


async def test_venue_search():
    """Test venue search functionality"""
    print("\n🏠 Testing Venue Search...")
    print("-" * 50)
    
    try:
        venues = await scraper.search_venues_parallel(
            location="Lake Tahoe, CA",
            checkin="2025-08-25",
            checkout="2025-08-30",
            adults=4,
            budget=300
        )
        
        print(f"Found {len(venues)} venues")
        if venues:
            print("\nFirst venue:")
            print(json.dumps(venues[0], indent=2))
        
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


async def test_flight_search():
    """Test flight search functionality"""
    print("\n✈️ Testing Flight Search...")
    print("-" * 50)
    
    try:
        result = await scraper.scrape_google_flights(
            origin="SFO",
            destination="RNO",
            departure_date="2025-08-25"
        )
        
        if result.get("success"):
            flights = result.get("data", {}).get("flights", [])
            print(f"Found {len(flights)} flights")
            if flights:
                print("\nFirst flight:")
                print(json.dumps(flights[0], indent=2))
        else:
            print(f"Error: {result.get('error')}")
        
        return result.get("success", False)
    except Exception as e:
        print(f"Error: {e}")
        return False


async def test_checkin():
    """Test check-in functionality (will fail without real confirmation)"""
    print("\n🎫 Testing Check-in...")
    print("-" * 50)
    print("Note: This will fail without a real confirmation code")
    
    try:
        result = await scraper.checkin_airline(
            airline="United",
            confirmation_code="TEST123",
            last_name="TestUser"
        )
        
        print(f"Result: {json.dumps(result, indent=2)}")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_state_management():
    """Test state management"""
    print("\n💾 Testing State Management...")
    print("-" * 50)
    
    try:
        # Create a test state
        state = TravelState("test_state.json")
        
        # Add a member
        member = Member(
            name="TestUser",
            location="SF",
            budget=2000
        )
        member.flight_criteria.airline = "United"
        member.flight_criteria.confirmation_code = "ABC123"
        member.flight_criteria.last_name = "Smith"
        
        state.members["TestUser"] = member
        state.save()
        
        print("✅ Created and saved test state")
        
        # Load it back
        state2 = TravelState("test_state.json")
        assert "TestUser" in state2.members
        assert state2.members["TestUser"].location == "SF"
        
        print("✅ Loaded state successfully")
        
        # Clean up
        import os
        if os.path.exists("test_state.json"):
            os.remove("test_state.json")
        
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_openai_helpers():
    """Test OpenAI helpers"""
    print("\n🤖 Testing OpenAI Helpers...")
    print("-" * 50)
    
    try:
        # Test venue criteria extraction
        criteria = extract_venue_criteria(
            "I want to stay in Lake Tahoe from Aug 25-30 with 4 people, budget $200 per night",
            {}
        )
        
        print("Venue criteria extracted:")
        print(json.dumps(criteria, indent=2))
        
        # Test flight criteria extraction
        flight_criteria = extract_flight_criteria(
            "I need to fly from SFO to RNO on August 25th, budget $300",
            "TestUser",
            {},
            {}
        )
        
        print("\nFlight criteria extracted:")
        print(json.dumps(flight_criteria, indent=2))
        
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


async def run_all_tests():
    """Run all tests"""
    print("=" * 50)
    print("🧪 Travel Planner Bot Test Suite")
    print("=" * 50)
    
    results = {}
    
    # Test state management (no API needed)
    results['state'] = test_state_management()
    
    # Test OpenAI helpers (needs API key)
    results['openai'] = test_openai_helpers()
    
    # Test Stagehand scrapers (needs API key and time)
    print("\n⚠️  Skipping Stagehand tests (uncomment to run)")
    print("These tests take 30-60 seconds each and require:")
    print("- OPENAI_API_KEY set in .env")
    print("- Node.js installed")
    print("- Chrome/Chromium installed")
    
    # Uncomment to run full tests:
    # results['venue'] = await test_venue_search()
    # results['flight'] = await test_flight_search()
    # results['checkin'] = await test_checkin()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name:15} {status}")
    
    all_passed = all(results.values())
    print("\n" + ("🎉 All tests passed!" if all_passed else "⚠️  Some tests failed"))


if __name__ == "__main__":
    asyncio.run(run_all_tests())






