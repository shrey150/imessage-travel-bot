import sys
import os
import logging

from imessage_bot_framework import Bot, Message
from imessage_bot_framework.decorators import command
import chromadb
from chromadb.config import Settings
from datetime import datetime
from typing import Optional, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger('travel_bot')

# Reduce noise from other loggers
logging.getLogger('chromadb').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('imessage_bot_framework').setLevel(logging.WARNING)

from config import (
    BOT_NAME, DEBUG,
    CHROMA_PERSIST_DIRECTORY, CHROMA_COLLECTION_NAME,
    MAX_VENUES_TO_STORE
)
from models import TravelState, BudgetEntry, Venue, Flight, Trip, SavedDocument
from openai_helpers import (
    extract_venue_criteria,
    extract_flight_criteria,
    answer_question_with_context,
    parse_budget_command,
    suggest_flight_alternatives
)
from stagehand_scraper import scraper
import asyncio
from datetime import datetime
import uuid

bot = Bot(BOT_NAME, debug=DEBUG)
state = TravelState()

pending_commands: Dict[str, Dict] = {}

scraped_urls = set(d.url for d in state.get_documents())

chroma_client = chromadb.PersistentClient(
    path=CHROMA_PERSIST_DIRECTORY,
    settings=Settings(anonymized_telemetry=False)
)

try:
    collection = chroma_client.get_collection(name=CHROMA_COLLECTION_NAME)
    logger.info(f"📂 Loaded existing Chroma collection with {collection.count()} messages")
except:
    collection = chroma_client.create_collection(
        name=CHROMA_COLLECTION_NAME,
        metadata={"description": "Trip planning conversation messages"}
    )
    logger.info("📂 Created new Chroma collection")


def index_message(message: Message):
    """Index a message to Chroma for semantic search"""
    try:
        # Only index if tracking is enabled and this is the tracked conversation
        if not state.trip or not state.trip.is_tracking:
            return
        
        chat_id = message.chat_guid
        
        if state.trip.tracked_conversation_id and chat_id != state.trip.tracked_conversation_id:
            return
        
        # Skip bot's own responses (starts with emojis or is a command response)
        if message.text.startswith(("✅", "❌", "🔍", "✈️", "📍", "💰", "🏠", "🤖", "⏸️", "🗑️")):
            return
        
        # Create unique ID for the message
        message_id = f"{message.sender}_{message.timestamp.isoformat() if hasattr(message.timestamp, 'isoformat') else str(message.timestamp)}"
        
        # Add to Chroma
        collection.add(
            documents=[message.text],
            metadatas=[{
                "sender": message.sender,
                "timestamp": message.timestamp.isoformat() if hasattr(message.timestamp, 'isoformat') else str(message.timestamp),
                "chat_id": chat_id or "unknown"
            }],
            ids=[message_id]
        )
        
        logger.info(f"📝 Indexed: \"{message.text[:60]}...\"")
            
    except Exception as e:
        logger.error(f"❌ Error indexing: {e}")


def search_messages(query: str, n_results: int = 10):
    """Semantic search for relevant messages"""
    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        # Format results
        messages = []
        if results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                messages.append({
                    "text": doc,
                    "sender": metadata.get("sender", "unknown"),
                    "timestamp": metadata.get("timestamp", "unknown")
                })
        
        return messages
    except Exception as e:
        if DEBUG:
            print(f"Error searching messages: {e}")
        return []


# Index all incoming messages automatically (if tracking is enabled)
@bot.on_message
def auto_index_messages(message: Message):
    """Automatically index messages if tracking is enabled, and auto-scrape known URLs"""
    # Check if message contains a known URL to auto-scrape
    text = message.text.strip()
    
    # Detect known domains
    known_domains = ["airbnb.com", "vrbo.com", "docs.google.com"]
    if any(domain in text for domain in known_domains):
        # Extract URL
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        
        for url in urls:
            # Check if it's a known domain
            if any(domain in url for domain in known_domains):
                # Check if already scraped (fast set lookup)
                if url in scraped_urls:
                    logger.info(f"⏭️  URL already scraped: {url}")
                    continue
                
                logger.info(f"🔗 Auto-detected new URL: {url}")
                # Auto-scrape in background (don't block)
                try:
                    result = auto_scrape_document(message, url)
                    if result:
                        # Add to scraped set
                        scraped_urls.add(url)
                        return result  # Return the save confirmation
                except Exception as e:
                    logger.error(f"❌ Error auto-scraping: {e}")
    
    # Regular message indexing
    index_message(message)
    return None  # Don't respond, just index


def auto_scrape_document(message: Message, url: str) -> Optional[str]:
    """Automatically scrape and save a detected URL"""
    logger.info(f"🤖 Auto-scraping: {url}")
    
    # Use the same save logic with auto_scraped flag
    return save_document_command(message, url, auto_scraped=True)


@bot.on_message
@command("!track")
def track_command(message: Message, args=None):
    """
    Start/stop tracking this conversation
    Usage: !track or !track stop
    """
    if args and args.lower() == "stop":
        # Stop tracking
        if state.trip:
            state.trip.is_tracking = False
            state.trip.tracked_conversation_id = None
            state.save()
            logger.info("🛑 Stopped tracking")
        return "⏸️ Stopped tracking messages. Use !track to start again."
    
    # Start tracking this conversation
    chat_id = message.chat_guid
    
    if not state.trip:
        state.trip = Trip(name="New Trip", is_tracking=True, tracked_conversation_id=chat_id)
    else:
        state.trip.is_tracking = True
        state.trip.tracked_conversation_id = chat_id
    
    state.save()
    logger.info(f"✅ Started tracking conversation: {chat_id}")
    
    return f"✅ Now tracking messages in this conversation!\n\nAll messages will be indexed for the !ask command.\nUse !track stop to stop tracking."


@bot.on_message
@command("!reset")
def reset_command(message: Message, args=None):
    """
    Reset the message index (clear all indexed messages)
    Usage: !reset
    """
    try:
        # Delete and recreate the collection
        chroma_client.delete_collection(name=CHROMA_COLLECTION_NAME)
        
        global collection
        collection = chroma_client.create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"description": "Trip planning conversation messages"}
        )
        
        logger.info("🗑️ Reset message index")
        return "🗑️ Message index reset! All indexed messages have been cleared.\n\nUse !track to start indexing messages again."
    except Exception as e:
        logger.error(f"❌ Error resetting index: {e}")
        return f"❌ Error resetting index: {str(e)}"


@bot.on_message
@command("!ask")
def ask_command(message: Message, args=None):
    """
    Free-form Q&A over conversation history and saved documents
    Usage: !ask what's the airbnb address?
    """
    if not args or not args.strip():
        return "What would you like to know? Example: !ask when does Shrey fly in?"
    
    logger.info(f"💬 Question: '{args}'")
    
    # Search for relevant messages AND documents
    relevant_messages = search_messages(args, n_results=10)
    logger.info(f"🔍 Found {len(relevant_messages)} relevant items (messages + docs) in index")
    
    # Get current state context including saved documents
    state_context = {
        "trip": state.trip.to_dict() if state.trip else {},
        "members": {name: member.to_dict() for name, member in state.members.items()},
        "venues": [v.to_dict() for v in state.get_venues()[:5]],  # Top 5 venues
        "flights": [f.to_dict() for f in state.get_flights()[:5]],  # Top 5 flights
        "saved_documents": [d.to_dict() for d in state.get_documents()],  # All saved docs
    }
    
    # Use OpenAI to answer
    logger.info("🤖 Asking OpenAI to answer...")
    answer = answer_question_with_context(args, relevant_messages, state_context)
    logger.info(f"✅ Generated answer")
    
    return answer


async def search_venues_background(criteria: Dict, chat_guid: str, sender: str):
    """Background task for venue search"""
    try:
        logger.info(f"🔄 Starting venue search...")
        venues_data = await scraper.search_venues_parallel(
            location=criteria.get("destination", ""),
            checkin=criteria.get("checkin", ""),
            checkout=criteria.get("checkout", ""),
            adults=criteria.get("adults", 2),
            budget=criteria.get("budget")
        )
        
        if not venues_data:
            logger.info("😕 No venues found matching criteria")
            bot.send_to_chat("😕 No venues found matching your criteria. Try adjusting your search!", chat_guid)
            return
        
        logger.info(f"✅ Found {len(venues_data)} total venues")
        
        # Clear old venues and create new Venue items
        logger.info(f"💾 Creating {min(len(venues_data), MAX_VENUES_TO_STORE)} venue items")
        state.clear_venues()
        state.venue_pagination_index = 3  # Start pagination after first 3 shown
        
        created_items = []
        for idx, venue_data in enumerate(venues_data[:MAX_VENUES_TO_STORE]):
            from models import Venue
            venue = Venue(
                title=venue_data.get("name", "Unknown Venue"),
                url=venue_data.get("url", ""),
                price_per_night=venue_data.get("pricePerNight"),
                total_price=venue_data.get("totalPrice"),
                rating=venue_data.get("rating"),
                review_count=venue_data.get("reviewCount"),
                image_url=venue_data.get("imageUrl"),
                amenities=venue_data.get("amenities", []),
                bedrooms=venue_data.get("bedrooms"),
                beds=venue_data.get("beds"),
                source=venue_data.get("source", "unknown"),
                created_by=sender
            )
            state.add_item(venue)
            created_items.append(venue)
        
        # Format result message - show first 3 with links
        result = f"🏠 Found {len(venues_data)} venues!\n\n"
        for venue in created_items[:3]:  # Show first 3
            result += f"{venue.id}. {venue.title}"
            if venue.price_per_night:
                result += f" - ${venue.price_per_night}/night"
            if venue.rating:
                result += f" ⭐ {venue.rating}"
            result += f"\n   🔗 {venue.url}\n"
        
        if len(created_items) > 3:
            result += f"\nShowing 3 of {len(created_items)}. Use !venue next for more."
        
        result += "\n\n💡 !show <number> for full details"
        result += "\n💡 !comment <number> <text> to share thoughts"
        if len(created_items) > 3:
            result += "\n💡 !venue next to see next 3"
        
        logger.info(f"✅ Created {len(created_items)} venue items")
        
        # Send message to user
        bot.send_to_chat(result, chat_guid)
        
    except Exception as e:
        error_msg = f"❌ Error in venue search: {e}"
        logger.error(error_msg)
        import traceback
        traceback.print_exc()
        bot.send_to_chat("❌ Sorry, something went wrong with the venue search. Please try again.", chat_guid)


@bot.on_message
@command("!venue")
def venue_command(message: Message, args=None):
    """
    Search for venues (Airbnb/Vrbo) or show next page
    Usage: !venue Lake Tahoe, 4 people, Aug 25-30
           !venue next
    Note: Just paste Airbnb/Vrbo/Google Doc links in chat - they're auto-saved!
    """
    if not args:
        return "Usage: !venue [search criteria]\nExample: !venue Lake Tahoe, 4 people, Aug 25-30\n\nOr: !venue next - Show next 3 venues\n\nTip: Just paste Airbnb/Vrbo/Google Doc links - they'll be auto-saved!"
    
    # Handle !venue next
    if args.strip().lower() == "next":
        venues = state.get_venues()
        if not venues:
            return "No venues to show. Use !venue to search first!"
        
        # Get next batch of 3
        start_idx = state.venue_pagination_index
        end_idx = min(start_idx + 3, len(venues))
        next_venues = venues[start_idx:end_idx]
        
        if not next_venues:
            # Reset to start
            state.venue_pagination_index = 0
            state.save()
            return f"You've seen all {len(venues)} venues! Resetting to start.\n\nUse !venue next to see the first 3 again, or !list venues to see all at once."
        
        # Update pagination index
        state.venue_pagination_index = end_idx
        state.save()
        
        # Format response
        response = f"🏠 Venues {start_idx + 1}-{end_idx} of {len(venues)}\n\n"
        for venue in next_venues:
            response += f"{venue.id}. {venue.title}"
            if venue.price_per_night:
                response += f" - ${venue.price_per_night}/night"
            if venue.rating:
                response += f" ⭐ {venue.rating}"
            response += f"\n   🔗 {venue.url}\n"
        
        if end_idx < len(venues):
            response += f"\n💡 !venue next for more ({len(venues) - end_idx} remaining)"
        else:
            response += f"\n✅ That's all! Use !list venues to see all"
        
        response += "\n💡 !show <number> for details | !comment <number> <text>"
        
        return response
    
    logger.info(f"🏠 Venue search: '{args}'")
    
    # Extract criteria
    trip_context = state.trip.to_dict() if state.trip else {}
    logger.info("🤖 Extracting search criteria with AI...")
    criteria = extract_venue_criteria(args or "", trip_context)
    
    # Check if we need clarification
    if criteria.get("needs_clarification"):
        logger.info("❓ Need clarification from user")
        return criteria.get("clarification_question", "Could you provide more details about the venue you're looking for?")
    
    logger.info(f"📋 Criteria: {criteria.get('destination')} | {criteria.get('checkin')} to {criteria.get('checkout')} | {criteria.get('adults')} people")
    
    # Spawn background task
    asyncio.create_task(search_venues_background(criteria, message.chat_guid, message.sender))
    
    return "🔍 Searching Airbnb and Vrbo in background, I'll notify you when ready..."


async def scrape_document_background(url: str, chat_guid: str, sender: str, auto_scraped: bool = False):
    """Background task that scrapes document and logs the results"""
    try:
        logger.info(f"🔄 Starting background scrape for: {url}")
        
        # Check if already exists
        existing = next((i for i in state.items if i.url == url), None)
        if existing:
            logger.info(f"⏭️  Already saved as Item #{existing.id}")
            bot.send_to_chat(f"ℹ️ Already saved as Item #{existing.id} ({existing.title})", chat_guid)
            return
        
        # Run the actual scraping
        result = await scraper.scrape_document(url)
        
        if not result.get("success"):
            error_msg = f"❌ Failed to scrape: {result.get('error')}"
            logger.error(error_msg)
            bot.send_to_chat("❌ Failed to scrape the document. Please check the URL and try again.", chat_guid)
            return
        
        data = result.get("data", {})
        logger.info(f"✅ Scraped document: {data.get('title')}")
        
        # Create Document item
        from models import Document
        doc = Document(
            title=data.get("title", "Untitled"),
            url=url,
            doc_type=data.get("documentType", "html"),
            structured_data=data.get("structuredData", {}),
            created_by=sender
        )
        
        state.add_item(doc)
        scraped_urls.add(url)
        logger.info(f"💾 Saved as Item #{doc.id}")
        
        # Index text chunks to Chroma
        text_chunks = data.get("textChunks", [])
        logger.info(f"📝 Indexing {len(text_chunks)} chunks to Chroma...")
        for idx, chunk in enumerate(text_chunks):
            try:
                collection.add(
                    documents=[chunk],
                    metadatas=[{
                        "type": "document",
                        "item_id": doc.id,
                        "url": url,
                        "doc_type": data.get("documentType", "html"),
                        "title": data.get("title", ""),
                        "saved_by": sender,
                        "chunk_index": idx
                    }],
                    ids=[f"item_{doc.id}_chunk_{idx}"]
                )
            except Exception as e:
                logger.error(f"❌ Error indexing chunk {idx}: {e}")
        
        logger.info("✅ Indexed to Chroma")
        
        # Build notification message with structured data
        structured = doc.structured_data
        message_parts = [f"✅ Saved as Item #{doc.id}: {doc.title}"]
        
        if structured.get("address"):
            message_parts.append(f"📍 {structured['address']}")
            logger.info(f"📍 {structured['address']}")
        if structured.get("checkInTime"):
            message_parts.append(f"🕐 Check-in: {structured['checkInTime']}")
            logger.info(f"🕐 Check-in: {structured['checkInTime']}")
        if structured.get("checkOutTime"):
            message_parts.append(f"🕐 Check-out: {structured['checkOutTime']}")
            logger.info(f"🕐 Check-out: {structured['checkOutTime']}")
        if structured.get("wifiNetwork"):
            wifi_info = f"📶 WiFi: {structured['wifiNetwork']}"
            if structured.get("wifiPassword"):
                wifi_info += f" / {structured['wifiPassword']}"
            message_parts.append(wifi_info)
            logger.info(wifi_info)
        if structured.get("accessCodes"):
            message_parts.append("🔑 Access codes:")
            logger.info("🔑 Access codes:")
            for code in structured['accessCodes']:
                code_info = f"  • {code['name']}: {code['code']}"
                message_parts.append(code_info)
                logger.info(code_info)
        if structured.get("phoneNumber"):
            message_parts.append(f"📞 Contact: {structured['phoneNumber']}")
            logger.info(f"📞 Contact: {structured['phoneNumber']}")
        
        message_parts.append(f"\n💡 Use !show {doc.id} for details | !ask to query")
        logger.info("📄 Full document indexed for !ask queries")
        
        # Send notification to user
        bot.send_to_chat("\n".join(message_parts), chat_guid)
        
    except Exception as e:
        error_msg = f"❌ Error in background scrape: {e}"
        logger.error(error_msg)
        import traceback
        traceback.print_exc()
        bot.send_to_chat("❌ Sorry, something went wrong while scraping the document.", chat_guid)


def save_document_command(message: Message, url: str, auto_scraped: bool = False) -> str:
    """Save a document URL - spawns background task"""
    from urllib.parse import urlparse
    
    # Validate URL using urllib.parse
    try:
        parsed = urlparse(url)
        if not all([parsed.scheme, parsed.netloc]) or parsed.scheme not in ['http', 'https']:
            return "❌ Invalid URL - must be a valid http/https URL"
    except Exception:
        return "❌ Invalid URL"
    
    # Check if already scraped
    if url in scraped_urls:
        return "⚠️ Already scraped this URL"
    
    logger.info(f"💾 {'Auto-' if auto_scraped else ''}Saving document: {url}")
    
    # Spawn background task
    asyncio.create_task(
        scrape_document_background(url, message.chat_guid, message.sender, auto_scraped)
    )
    
    return "🔄 Scraping in progress, I'll notify you when ready..."




@bot.on_message
@command("!flight")
def flight_command(message: Message, args=None):
    """
    Search for flights
    Usage: !flight Shrey from SFO to RNO on Aug 25
    """
    logger.info(f"✈️ Flight search: '{args}'")
    
    # Extract member name and criteria
    member_name = message.sender  # Default to sender
    # TODO: Parse member name from args if specified
    
    member = state.get_or_create_member(member_name)
    trip_context = state.trip.to_dict() if state.trip else {}
    member_context = member.to_dict()
    
    logger.info(f"🤖 Extracting flight criteria for {member_name}...")
    criteria = extract_flight_criteria(args or "", member_name, trip_context, member_context)
    
    # Check if we need clarification
    if criteria.get("needs_clarification"):
        logger.info("❓ Need clarification from user")
        return criteria.get("clarification_question", "Could you provide more details about the flight?")
    
    logger.info(f"📋 Flight criteria: {criteria.get('origin')} → {criteria.get('destination')} on {criteria.get('departure_date')}")
    
    # Spawn background task
    asyncio.create_task(search_flights_background(criteria, message.chat_guid, member_name, member.budget))
    
    return "🔍 Searching Google Flights in background, I'll notify you when ready..."


async def search_flights_background(criteria: Dict, chat_guid: str, member_name: str, member_budget: Optional[float]):
    """Background task for flight search"""
    try:
        origin = criteria.get("origin", "")
        destination = criteria.get("destination", "")
        departure_date = criteria.get("departure_date", "")
        return_date = criteria.get("return_date")
        
        logger.info(f"🔍 Flight async search - From: {origin}, To: {destination}, Date: {departure_date}")
        
        if not origin or not destination or not departure_date:
            logger.error(f"❌ Missing required criteria")
            bot.send_to_chat("❌ Missing required flight information. Please try again.", chat_guid)
            return
        
        result = await scraper.scrape_google_flights(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date
        )
        
        if not result.get("success"):
            logger.error(f"❌ Scraper failed: {result.get('error', 'Unknown error')}")
            bot.send_to_chat("❌ Failed to search flights. Please try again later.", chat_guid)
            return
        
        flights = result.get("data", {}).get("flights", [])
        logger.info(f"✅ Scraper returned {len(flights)} flights")
        
        if not flights:
            logger.info("😕 No flights found")
            suggestions = suggest_flight_alternatives(criteria, "no_availability")
            bot.send_to_chat(f"😕 No flights found. {suggestions}", chat_guid)
            return
        
        # Check budget
        if member_budget:
            affordable_flights = [f for f in flights if f.get("price", 0) <= member_budget]
            if not affordable_flights:
                logger.info(f"💰 No flights within ${member_budget} budget")
                suggestions = suggest_flight_alternatives(criteria, "budget")
                bot.send_to_chat(f"💰 No flights within ${member_budget} budget. {suggestions}", chat_guid)
                return
            logger.info(f"✅ {len(affordable_flights)} flights within budget")
            flights = affordable_flights
        
        # Store flights in state as items
        logger.info(f"💾 Storing top {min(len(flights), 5)} flights for {member_name}")
        from models import Flight
        for idx, flight_data in enumerate(flights[:5]):  # Top 5
            route = f"{flight_data.get('departureAirport', 'unknown')}->{flight_data.get('arrivalAirport', 'unknown')}"
            airline = flight_data.get("airline", "Unknown")
            flight_num = flight_data.get("flightNumber", "")
            title = f"{airline} {flight_num} - {route}" if flight_num else f"{airline} - {route}"
            
            flight = Flight(
                title=title,
                url=flight_data.get("url", ""),
                member=member_name,
                route=route,
                airline=airline,
                flight_number=flight_num,
                departure_time=flight_data.get("departureTime"),
                arrival_time=flight_data.get("arrivalTime"),
                duration=flight_data.get("duration"),
                stops=flight_data.get("stops", 0),
                price=flight_data.get("price"),
                created_by=member_name
            )
            state.add_item(flight)
        
        # Format response
        response = f"✈️ Found {len(flights)} flights for {member_name}!\n\n"
        recent_flights = [f for f in state.get_flights() if f.member == member_name][-5:]  # Last 5 for this member
        
        for flight in recent_flights:
            response += f"{flight.id}. {flight.airline or 'Unknown'}"
            if flight.flight_number:
                response += f" {flight.flight_number}"
            response += f"\n"
            response += f"   {flight.route}"
            if flight.departure_time:
                response += f" at {flight.departure_time}"
            response += f"\n"
            if flight.duration:
                response += f"   ⏱️ {flight.duration}"
            if flight.stops == 0:
                response += " (nonstop)"
            elif flight.stops:
                response += f" ({flight.stops} stop{'s' if flight.stops > 1 else ''})"
            response += f"\n"
            if flight.price:
                response += f"   💰 ${flight.price:.2f}\n"
            if flight.url:
                response += f"   🔗 {flight.url}\n"
            response += "\n"
        
        response += f"💡 Use !show <number> for details | !list flights to see all"
        
        logger.info(f"✅ Sending flight results to user")
        bot.send_to_chat(response, chat_guid)
        
    except Exception as e:
        logger.error(f"❌ Flight search error: {e}")
        bot.send_to_chat(f"❌ Error searching flights: {str(e)}", chat_guid)


@bot.on_message
@command("!doc")
def doc_command(message: Message, args=None):
    """
    Mark document(s) as official for the trip
    Usage: !doc use 1 or !doc use the airbnb called Beautiful Place
    """
    if not args:
        # Show list of docs to choose from
        docs = state.get_documents()
        if not docs:
            return "📄 No saved documents yet.\n\n💡 Paste Airbnb/Vrbo/Google Doc links in chat - they'll be auto-saved!"
        
        response = f"📄 Saved Documents ({len(docs)}):\n\n"
        for idx, d in enumerate(docs, 1):
            official = " ⭐" if d.is_official else ""
            response += f"{idx}. {d.title}{official}\n"
            response += f"   Type: {d.doc_type}\n"
            if d.structured_data.get("address"):
                response += f"   📍 {d.structured_data['address'][:50]}...\n"
            response += "\n"
        
        response += "Usage:\n"
        response += "• !doc use <number> - Mark as official\n"
        response += "• !doc remove <number> - Unmark as official\n"
        response += "• !doc use <description> - Find & mark by description"
        
        return response
    
    args_lower = args.strip().lower()
    
    # Handle remove/unuse
    if args_lower.startswith("remove") or args_lower.startswith("unuse"):
        criteria = args.split(maxsplit=1)[1].strip() if len(args.split(maxsplit=1)) > 1 else ""
        
        if not criteria:
            return "Usage: !doc remove <number>\nExample: !doc remove 1"
        
        # Try to parse as number
        try:
            index = int(criteria) - 1
            docs = state.get_documents()
            if 0 <= index < len(docs):
                doc = docs[index]
                if doc.is_official:
                    doc.is_official = False
                    state.save()
                    logger.info(f"❌ Unmarked: {doc.title}")
                    return f"✅ Unmarked: {doc.title}\n\nIt's still saved, just not marked as official anymore."
                else:
                    return f"ℹ️  '{doc.title}' wasn't marked as official."
            else:
                return f"❌ Invalid document number. Use !doc to see all documents."
        except ValueError:
            return "❌ Please provide a valid number. Example: !doc remove 2"
    
    # Explicit number(s)
    if args_lower.startswith("use"):
        criteria = args[3:].strip()  # Remove "use"
        
        # Try to parse as numbers
        import re
        numbers = re.findall(r'\d+', criteria)
        
        if numbers:
            # Explicit number selection
            marked = []
            docs = state.get_documents()
            for num_str in numbers:
                try:
                    index = int(num_str) - 1
                    if 0 <= index < len(docs):
                        doc = docs[index]
                        if state.mark_document_as_official(doc.id):
                            marked.append(doc.title)
                            logger.info(f"✅ Marked as official: {doc.title}")
                except ValueError:
                    continue
            
            if marked:
                response = "✅ Marked as official:\n"
                for title in marked:
                    response += f"  • {title}\n"
                return response
            else:
                return "❌ Invalid document number(s). Use !docs to see all documents."
        
        else:
            # Natural language search
            logger.info(f"🔍 Searching for document: '{criteria}'")
            
            # Show all docs to help user debug
            docs = state.get_documents()
            logger.info(f"📄 Available docs: {[d.title for d in docs]}")
            
            # Use OpenAI to find matching document
            from openai_helpers import find_matching_document
            doc_id = find_matching_document(criteria, docs)
            
            if doc_id:
                doc = next((d for d in docs if d.id == doc_id), None)
                if doc:
                    logger.info(f"🎯 AI matched: '{doc.title}' (type: {doc.doc_type})")
                    
                    # Confirm it's the right type
                    if "airbnb" in criteria.lower() and doc.doc_type != "airbnb":
                        logger.warning(f"⚠️  Type mismatch! User asked for airbnb, got {doc.doc_type}")
                        return f"❌ Found '{doc.title}' but it's a {doc.doc_type}, not an Airbnb.\n\nUse !docs to see all documents."
                    if "vrbo" in criteria.lower() and doc.doc_type != "vrbo":
                        logger.warning(f"⚠️  Type mismatch! User asked for vrbo, got {doc.doc_type}")
                        return f"❌ Found '{doc.title}' but it's a {doc.doc_type}, not a Vrbo.\n\nUse !docs to see all documents."
                    if "google doc" in criteria.lower() and doc.doc_type != "google_doc":
                        logger.warning(f"⚠️  Type mismatch! User asked for google doc, got {doc.doc_type}")
                        return f"❌ Found '{doc.title}' but it's a {doc.doc_type}, not a Google Doc.\n\nUse !docs to see all documents."
                    
                    if state.mark_document_as_official(doc_id):
                        logger.info(f"✅ Marked as official via NL: {doc.title}")
                        return f"✅ Marked as official: {doc.title}"
            
            logger.warning(f"❌ No match found for: '{criteria}'")
            
            # Show all docs to help user choose
            response = f"❌ Couldn't find a document matching: '{criteria}'\n\n"
            response += f"📄 Available Documents:\n\n"
            
            docs = state.get_documents()
            for idx, d in enumerate(docs, 1):
                official = " ⭐" if d.is_official else ""
                response += f"{idx}. {d.title}{official}\n"
                response += f"   Type: {d.doc_type}\n"
                if d.structured_data.get("address"):
                    response += f"   📍 {d.structured_data['address'][:50]}...\n"
                response += "\n"
            
            response += "Use !doc use <number> to select by number"
            return response
    
    return "Usage: !doc use <number> or !doc use <description>"


@bot.on_message
@command("!docs")
def docs_command(message: Message, args=None):
    """
    List or manage saved documents
    Usage: !docs or !docs clear or !docs delete <number>
    """
    logger.info(f"📄 !docs command called with args: '{args}'")
    
    # Handle delete specific document
    if args and args.lower().startswith("delete"):
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: !docs delete <number>\nExample: !docs delete 1"
        
        try:
            index = int(parts[1]) - 1  # Convert to 0-based index
            docs = state.get_documents()
            
            if index < 0 or index >= len(docs):
                return f"❌ Invalid document number. Use !docs to see all documents (1-{len(docs)})"
            
            # Get the document to delete
            doc_to_delete = docs[index]
            doc_title = doc_to_delete.title
            doc_id = doc_to_delete.id
            
            # Remove from state and cache
            state.delete_item(doc_id)
            scraped_urls.discard(doc_to_delete.url)  # Remove from cache
            
            # Remove chunks from Chroma
            try:
                all_results = collection.get()
                if all_results and all_results['ids']:
                    doc_chunk_ids = [id for id in all_results['ids'] if id.startswith(f"{doc_id}_chunk_")]
                    if doc_chunk_ids:
                        collection.delete(ids=doc_chunk_ids)
                        logger.info(f"🗑️ Deleted {len(doc_chunk_ids)} chunks for: {doc_title}")
            except Exception as e:
                logger.error(f"Error deleting document chunks from Chroma: {e}")
            
            logger.info(f"🗑️ Deleted document: {doc_title}")
            return f"🗑️ Deleted: {doc_title}"
            
        except ValueError:
            return "❌ Please provide a valid number. Example: !docs delete 2"
    
    # Handle clear all documents
    if args and args.lower() == "clear":
        # Clear all documents
        count = len(state.get_documents())
        scraped_urls.clear()  # Clear cache
        state.clear_saved_documents()
        
        # Also clear document chunks from Chroma
        try:
            # Get all document IDs from collection
            all_results = collection.get()
            if all_results and all_results['ids']:
                doc_ids = [id for id in all_results['ids'] if '_chunk_' in id]
                if doc_ids:
                    collection.delete(ids=doc_ids)
                    logger.info(f"🗑️ Cleared {len(doc_ids)} document chunks from Chroma")
        except Exception as e:
            logger.error(f"Error clearing documents from Chroma: {e}")
        
        logger.info(f"🗑️ Cleared {count} saved documents")
        return f"🗑️ Cleared {count} saved document(s) and their indexed content."
    
    # List all saved documents
    docs = state.get_documents()
    if not docs:
        return "📄 No saved documents yet.\n\n💡 Tip: Just paste Airbnb/Vrbo/Google Doc links in chat - they'll be auto-saved!"
    
    response = f"📄 Saved Documents ({len(docs)}):\n\n"
    
    for idx, doc in enumerate(docs, 1):
        # Mark official docs
        official_marker = " ⭐ OFFICIAL" if doc.is_official else ""
        response += f"{idx}. {doc.title}{official_marker}\n"
        response += f"   Type: {doc.doc_type}\n"
        response += f"   Saved by: {doc.saved_by}\n"
        
        # Show key structured data if available
        if doc.structured_data.get("address"):
            response += f"   📍 {doc.structured_data['address']}\n"
        if doc.structured_data.get("wifiNetwork"):
            response += f"   📶 {doc.structured_data['wifiNetwork']}\n"
        if doc.structured_data.get("accessCodes"):
            codes_count = len(doc.structured_data['accessCodes'])
            response += f"   🔑 {codes_count} access code(s)\n"
        
        response += f"   🔗 {doc.url}\n\n"
    
    response += "Commands:\n"
    response += "• !doc use <number> - Mark as official\n"
    response += "• !doc remove <number> - Unmark as official\n"
    response += "• !docs delete <number> - Delete document completely\n"
    response += "• !docs clear - Delete all documents"
    
    return response


@bot.on_message
@command("!trip")
def trip_command(message: Message, args=None):
    """
    Show official trip details from marked items (venues, documents)
    Usage: !trip
    """
    from models import Venue, Document
    
    # Get all official items (Venues and Documents)
    official_items = [item for item in state.items if item.is_official]
    
    if not official_items:
        return "📋 No official items marked yet.\n\nUse !official <number> to mark venues or documents as official.\nExample: !official 16"
    
    response = "📋 Official Trip Details:\n\n"
    
    for item in official_items:
        if isinstance(item, Venue):
            # Show venue details
            response += f"🏠 {item.title}\n"
            response += f"   Source: {item.source}\n"
            if item.price_per_night:
                response += f"   💰 ${item.price_per_night}/night"
                if item.total_price:
                    response += f" (${item.total_price} total)"
                response += "\n"
            if item.bedrooms:
                response += f"   🛏️ {item.bedrooms} bedroom{'s' if item.bedrooms > 1 else ''}"
                if item.beds:
                    response += f", {item.beds} bed{'s' if item.beds > 1 else ''}"
                response += "\n"
            if item.rating:
                response += f"   ⭐ {item.rating}/5"
                if item.review_count:
                    response += f" ({item.review_count} reviews)"
                response += "\n"
            
            # Show structured data if available
            if item.structured_data:
                data = item.structured_data
                if data.get("address"):
                    response += f"   📍 {data['address']}\n"
                if data.get("checkInTime"):
                    response += f"   🕐 Check-in: {data['checkInTime']}\n"
                if data.get("checkOutTime"):
                    response += f"   🕐 Check-out: {data['checkOutTime']}\n"
                if data.get("wifiNetwork"):
                    wifi = f"   📶 WiFi: {data['wifiNetwork']}"
                    if data.get("wifiPassword"):
                        wifi += f" / {data['wifiPassword']}"
                    response += wifi + "\n"
                if data.get("phoneNumber"):
                    response += f"   📞 {data['phoneNumber']}\n"
                if data.get("accessCodes"):
                    response += f"   🔑 Access codes:\n"
                    for code in data['accessCodes']:
                        response += f"      • {code['name']}: {code['code']}\n"
            
            if item.url:
                response += f"   🔗 {item.url}\n"
            response += "\n"
            
        elif isinstance(item, Document):
            # Show document details
            response += f"📄 {item.title}\n"
            response += f"   Type: {item.doc_type}\n"
            
            # Show structured data
            data = item.structured_data
            if data.get("address"):
                response += f"   📍 {data['address']}\n"
            if data.get("checkInTime"):
                response += f"   🕐 Check-in: {data['checkInTime']}\n"
            if data.get("checkOutTime"):
                response += f"   🕐 Check-out: {data['checkOutTime']}\n"
            if data.get("wifiNetwork"):
                wifi = f"   📶 WiFi: {data['wifiNetwork']}"
                if data.get("wifiPassword"):
                    wifi += f" / {data['wifiPassword']}"
                response += wifi + "\n"
            if data.get("phoneNumber"):
                response += f"   📞 {data['phoneNumber']}\n"
            if data.get("accessCodes"):
                response += f"   🔑 Access codes:\n"
                for code in data['accessCodes']:
                    response += f"      • {code['name']}: {code['code']}\n"
            
            if item.url:
                response += f"   🔗 {item.url}\n"
            response += "\n"
    
    response += "💡 Tip: Use !ask to query all trip details!"
    
    return response


@bot.on_message
@command("!budget")
def budget_command(message: Message, args=None):
    """
    Track and show budget
    Usage: !budget show, !budget set 5000, or !budget add airbnb 500
    """
    if not args:
        args = "show"
    
    # Handle set budget
    if args.strip().lower().startswith("set"):
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: !budget set <amount>\nExample: !budget set 5000"
        
        try:
            amount = float(parts[1].replace("$", "").replace(",", ""))
            if amount <= 0:
                return "❌ Budget must be positive"
            
            if not state.trip:
                state.trip = Trip(name="New Trip", total_budget=amount)
            else:
                state.trip.total_budget = amount
            
            state.save()
            logger.info(f"💰 Set trip budget: ${amount}")
            return f"✅ Set trip budget to ${amount:,.2f}"
            
        except ValueError:
            return "❌ Invalid amount. Example: !budget set 5000"
    
    parsed = parse_budget_command(f"!budget {args}")
    action = parsed.get("action", "show")
    
    if action == "show":
        # Display budget summary
        trip_budget = state.trip.total_budget if state.trip else None
        total_spent = state.get_total_spent()
        
        response = "💰 Budget Summary\n"
        
        if trip_budget:
            remaining = trip_budget - total_spent
            response += f"Total Budget: ${trip_budget:,.2f}\n"
            response += f"Total Spent: ${total_spent:,.2f}\n"
            response += f"Remaining: ${remaining:,.2f}\n"
            
            # Show progress bar
            if trip_budget > 0:
                percent = min(100, (total_spent / trip_budget) * 100)
                bar_length = 20
                filled = int(bar_length * percent / 100)
                bar = "█" * filled + "░" * (bar_length - filled)
                response += f"Progress: [{bar}] {percent:.0f}%\n"
        else:
            response += f"Total Spent: ${total_spent:,.2f}\n"
            response += "💡 Set a budget with: !budget set <amount>\n"
        
        response += "\n"
        
        if state.budget_ledger:
            response += "Expenses:\n"
            for entry in state.budget_ledger:
                response += f"• {entry.item}: ${entry.amount:.2f} ({entry.paid_by})\n"
        else:
            response += "No expenses recorded yet."
        
        return response
    
    elif action == "add":
        # Add budget entry
        item = parsed.get("item", "expense")
        amount = parsed.get("amount", 0)
        notes = parsed.get("notes")
        
        if amount <= 0:
            return "Please provide a valid amount. Example: !budget add airbnb 500"
        
        entry = BudgetEntry(
            item=item,
            amount=amount,
            date=datetime.now().isoformat(),
            paid_by=message.sender,
            notes=notes
        )
        
        state.add_budget_entry(entry)
        return f"✅ Added ${amount:.2f} for {item} to the budget!"
    
    return "Usage: !budget show or !budget add [item] [amount]"


@bot.on_message
@command("!list")
def list_command(message: Message, args=None):
    """
    List all saved items (venues, documents, flights)
    Usage: !list or !list venues or !list docs or !list official
    """
    filter_type = args.strip().lower() if args else "all"
    
    # Get filtered items
    if filter_type == "venues":
        items = state.get_venues()
        title = "🏠 Venues"
    elif filter_type in ["docs", "documents"]:
        items = state.get_documents()
        title = "📄 Documents"
    elif filter_type == "flights":
        items = state.get_flights()
        title = "✈️  Flights"
    elif filter_type == "official":
        items = [i for i in state.items if i.is_official]
        title = "⭐ Official Items"
    else:
        items = state.items
        title = f"📋 All Items ({len(items)})"
    
    if not items:
        return f"No items found. Use !venue to search for accommodations or paste a link to save!"
    
    # Group by type for "all" view
    if filter_type == "all":
        venues = state.get_venues()
        docs = state.get_documents()
        flights = state.get_flights()
        
        response = f"{title}\n\n"
        
        if venues:
            response += "Venues:\n"
            for v in venues[:10]:  # Show max 10
                official = " ⭐" if v.is_official else ""
                price_info = f" - ${v.price_per_night}/night" if v.price_per_night else ""
                rating_info = f" ⭐ {v.rating}" if v.rating else ""
                response += f"{v.id}. {v.title}{price_info}{rating_info}{official}\n"
            if len(venues) > 10:
                response += f"   (+ {len(venues) - 10} more)\n"
            response += "\n"
        
        if docs:
            response += "Documents:\n"
            for d in docs[:10]:
                official = " ⭐" if d.is_official else ""
                response += f"{d.id}. {d.title} ({d.doc_type}){official}\n"
            if len(docs) > 10:
                response += f"   (+ {len(docs) - 10} more)\n"
            response += "\n"
        
        if flights:
            response += "Flights:\n"
            for f in flights[:10]:
                price_info = f" - ${f.price}" if f.price else ""
                response += f"{f.id}. {f.title}{price_info}\n"
            if len(flights) > 10:
                response += f"   (+ {len(flights) - 10} more)\n"
            response += "\n"
    else:
        # Filtered view - show more detail
        response = f"{title} ({len(items)})\n\n"
        for item in items[:20]:  # Show max 20
            official = " ⭐" if item.is_official else ""
            
            if isinstance(item, Venue):
                from models import Venue
                price_info = f" - ${item.price_per_night}/night" if item.price_per_night else ""
                rating_info = f" ⭐ {item.rating}" if item.rating else ""
                response += f"{item.id}. {item.title}{price_info}{rating_info}{official}\n"
            elif isinstance(item, Document):
                from models import Document
                response += f"{item.id}. {item.title} ({item.doc_type}){official}\n"
            elif isinstance(item, Flight):
                from models import Flight
                price_info = f" - ${item.price}" if item.price else ""
                response += f"{item.id}. {item.title}{price_info}{official}\n"
            else:
                response += f"{item.id}. {item.title}{official}\n"
        
        if len(items) > 20:
            response += f"\n(+ {len(items) - 20} more)\n"
    
    response += "\n💡 !show <number> for details | !comment <number> <text> to add feedback"
    return response


@bot.on_message
@command("!show")
def show_command(message: Message, args=None):
    """
    Show details for a specific item
    Usage: !show <id>
    """
    if not args or not args.strip().isdigit():
        return "Usage: !show <number>\nExample: !show 3"
    
    item_id = int(args.strip())
    item = state.get_item_by_id(item_id)
    
    if not item:
        return f"❌ Item #{item_id} not found. Use !list to see all items."
    
    from models import Venue, Document, Flight
    
    # Build response based on item type
    official = " ⭐" if item.is_official else ""
    response = f"📍 Item #{item.id}: {item.title}{official}\n\n"
    
    if isinstance(item, Venue):
        response += f"Type: {item.source.capitalize()} Venue\n"
        if item.price_per_night:
            response += f"Price: ${item.price_per_night}/night"
            if item.total_price:
                response += f" (${item.total_price:.0f} total)"
            response += "\n"
        if item.rating:
            response += f"Rating: ⭐ {item.rating}"
            if item.review_count:
                response += f" ({item.review_count} reviews)"
            response += "\n"
        if item.bedrooms:
            response += f"Bedrooms: {item.bedrooms}"
            if item.beds:
                response += f" | Beds: {item.beds}"
            response += "\n"
        if item.amenities:
            response += f"Amenities: {', '.join(item.amenities[:5])}"
            if len(item.amenities) > 5:
                response += f" (+ {len(item.amenities) - 5} more)"
            response += "\n"
    
    elif isinstance(item, Document):
        response += f"Type: {item.doc_type.replace('_', ' ').title()} Document\n"
        if item.structured_data.get("address"):
            response += f"📍 {item.structured_data['address']}\n"
        if item.structured_data.get("checkInTime"):
            response += f"🕐 Check-in: {item.structured_data['checkInTime']}\n"
        if item.structured_data.get("checkOutTime"):
            response += f"🕐 Check-out: {item.structured_data['checkOutTime']}\n"
        if item.structured_data.get("wifiNetwork"):
            response += f"📶 WiFi: {item.structured_data['wifiNetwork']}"
            if item.structured_data.get("wifiPassword"):
                response += f" / {item.structured_data['wifiPassword']}"
            response += "\n"
    
    elif isinstance(item, Flight):
        response += f"Type: Flight\n"
        if item.member:
            response += f"Passenger: {item.member}\n"
        if item.route:
            response += f"Route: {item.route}\n"
        if item.departure_time:
            response += f"Departure: {item.departure_time}\n"
        if item.arrival_time:
            response += f"Arrival: {item.arrival_time}\n"
        if item.duration:
            response += f"Duration: {item.duration}\n"
        if item.stops == 0:
            response += "Nonstop\n"
        elif item.stops:
            response += f"Stops: {item.stops}\n"
        if item.price:
            response += f"💰 ${item.price:.2f}\n"
    
    if item.url:
        response += f"🔗 {item.url}\n"
    
    # Show comments
    if item.comments:
        response += f"\n💬 Comments ({len(item.comments)}):\n"
        for comment in item.comments:
            response += f"• {comment['user']}: {comment['text']}\n"
    
    response += f"\n💡 !comment {item.id} <text> | !official {item.id}"
    
    return response


@bot.on_message
@command("!comment")
def comment_command(message: Message, args=None):
    """
    Add a comment/feedback to an item
    Usage: !comment <id> <text>
    """
    if not args or not args.strip():
        return "Usage: !comment <number> <your comment>\nExample: !comment 3 Love this place!"
    
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "Usage: !comment <number> <your comment>\nExample: !comment 3 Love this place!"
    
    item_id = int(parts[0])
    comment_text = parts[1]
    
    item = state.get_item_by_id(item_id)
    if not item:
        return f"❌ Item #{item_id} not found. Use !list to see all items."
    
    # Add comment
    item.add_comment(message.sender, comment_text)
    state.save()
    state._trigger_sync()  # Trigger sync after comment
    
    # Index comment to Chroma
    try:
        collection.add(
            documents=[f"{message.sender} commented on {item.title}: {comment_text}"],
            metadatas=[{
                "type": "comment",
                "item_id": item.id,
                "user": message.sender,
                "timestamp": datetime.now().isoformat()
            }],
            ids=[f"item_{item.id}_comment_{len(item.comments)-1}"]
        )
    except Exception as e:
        logger.error(f"Error indexing comment: {e}")
    
    logger.info(f"💬 {message.sender} commented on Item #{item.id}: {comment_text}")
    return f"✅ Added your comment to Item #{item.id} ({item.title})"


@bot.on_message
@command("!official")
def official_command(message: Message, args=None):
    """
    Mark item(s) as official for the trip
    Usage: !official <id> [id2] [id3]...
    Example: !official 16 or !official 16 23 45
    """
    if not args:
        return "Usage: !official <number> [number2] [number3]...\nExample: !official 16\nExample: !official 16 23 45"
    
    from models import Document, Venue
    import re
    
    # Parse all numbers from args
    item_ids = [int(x) for x in re.findall(r'\d+', args)]
    
    if not item_ids:
        return "Usage: !official <number> [number2] [number3]...\nExample: !official 16"
    
    marked = []
    not_found = []
    venue_url_to_scrape = None
    
    for item_id in item_ids:
        item = state.get_item_by_id(item_id)
        
        if not item:
            not_found.append(item_id)
            continue
        
        # Special handling for accommodations (Venues and Airbnb/Vrbo Documents)
        # Only allow ONE official accommodation at a time
        is_accommodation = (
            isinstance(item, Venue) or 
            (isinstance(item, Document) and item.doc_type in ["airbnb", "vrbo"])
        )
        
        if is_accommodation:
            # Unmark other accommodations
            for other_item in state.items:
                if other_item.id not in item_ids:  # Don't unmark items we're about to mark
                    is_other_accommodation = (
                        isinstance(other_item, Venue) or 
                        (isinstance(other_item, Document) and other_item.doc_type in ["airbnb", "vrbo"])
                    )
                    if is_other_accommodation and other_item.is_official:
                        other_item.is_official = False
                        logger.info(f"⭐ Auto-unmarked previous accommodation: {other_item.title}")
        
        # Mark this item as official
        item.is_official = True
        marked.append(item)
        logger.info(f"⭐ Marked Item #{item.id} as official: {item.title}")
        
        # If it's a Venue with a URL and we haven't scraped it yet, save it
        if isinstance(item, Venue) and item.url and item.url not in scraped_urls:
            venue_url_to_scrape = item.url
    
    state.save()
    
    # Build response
    if not marked and not_found:
        return f"❌ Item(s) not found: {', '.join(map(str, not_found))}. Use !list to see all items."
    
    response = "⭐ Marked as official:\n"
    for item in marked:
        item_type = "🏠" if isinstance(item, Venue) else "📄"
        response += f"{item_type} Item #{item.id}: {item.title}\n"
    
    if not_found:
        response += f"\n❌ Not found: {', '.join(map(str, not_found))}"
    
    # If there's a venue URL to scrape, suggest it
    if venue_url_to_scrape:
        response += f"\n\n💡 Want full logistics (WiFi, access codes, etc.)?\nPaste the URL to auto-scrape:\n{venue_url_to_scrape}"
    
    return response


@bot.on_message
@command("!delete")
def delete_command(message: Message, args=None):
    """
    Delete an item
    Usage: !delete <id>
    """
    if not args or not args.strip().isdigit():
        return "Usage: !delete <number>\nExample: !delete 5"
    
    item_id = int(args.strip())
    item = state.get_item_by_id(item_id)
    
    if not item:
        return f"❌ Item #{item_id} not found."
    
    item_title = item.title
    
    # Delete from Chroma
    try:
        # Find all chunks related to this item
        all_results = collection.get()
        if all_results and all_results['ids']:
            item_chunk_ids = [id for id in all_results['ids'] if f"item_{item_id}_" in id]
            if item_chunk_ids:
                collection.delete(ids=item_chunk_ids)
                logger.info(f"🗑️ Deleted {len(item_chunk_ids)} Chroma chunks for Item #{item_id}")
    except Exception as e:
        logger.error(f"Error deleting from Chroma: {e}")
    
    # Delete from state
    if state.delete_item(item_id):
        logger.info(f"🗑️ Deleted Item #{item_id}: {item_title}")
        return f"🗑️ Deleted Item #{item_id} ({item_title})"
    else:
        return f"❌ Failed to delete Item #{item_id}"


async def test_and_sync_background(doc_url: str, chat_guid: str):
    """Background task to test permissions and do initial sync"""
    try:
        logger.info("🔄 Testing doc permissions and syncing...")
        
        # Trigger the sync
        state._trigger_sync()
        
        # Wait a bit for sync to complete
        await asyncio.sleep(35)
        
        # Check result
        if state.sync_config.last_sync_status == "success":
            bot.send_to_chat(
                f"✅ Connected to Google Doc!\n\nAuto-sync enabled ✨\n\nThe doc will update when you:\n• Add venues/docs/flights\n• Add comments (!comment)\n• Mark items official (!official)\n• Update budget\n\nView: {doc_url}",
                chat_guid
            )
        elif state.sync_config.last_sync_status == "failed":
            bot.send_to_chat(
                f"❌ Could not sync to document.\n\nPlease check:\n1. Doc is set to 'Anyone with link can EDIT'\n2. URL is correct: {doc_url}\n3. Try !sync now to retry",
                chat_guid
            )
    except Exception as e:
        logger.error(f"Error in setup sync: {e}")
        bot.send_to_chat("❌ Error connecting to Google Doc. Use !sync status to check.", chat_guid)


@bot.on_message
@command("!sync")
def sync_command(message: Message, args=None):
    """
    Manage Google Doc sync
    Usage:
      !sync setup <url> - Connect to a Google Doc
      !sync now - Force sync now
      !sync status - Show sync status
      !sync enable/disable - Toggle auto-sync
    """
    if not args:
        # Show status
        if state.sync_config.doc_url:
            status = f"📄 Connected Doc:\n{state.sync_config.doc_url}\n\n"
            status += f"Auto-sync: {'✅ Enabled' if state.sync_config.enabled else '❌ Disabled'}\n"
            if state.sync_config.last_sync_at:
                from datetime import datetime
                try:
                    sync_dt = datetime.fromisoformat(state.sync_config.last_sync_at)
                    time_str = sync_dt.strftime("%b %d at %I:%M %p")
                    status += f"Last sync: {time_str} ({state.sync_config.last_sync_status})\n"
                except:
                    status += f"Last sync: {state.sync_config.last_sync_at} ({state.sync_config.last_sync_status})\n"
            else:
                status += "Last sync: Never\n"
            
            status += f"\nCommands:\n"
            status += "• !sync now - Force sync\n"
            status += "• !sync enable/disable - Toggle auto-sync"
            
            return status
        else:
            return "No Google Doc connected.\n\nUsage: !sync setup <url>\n\n1. Create a Google Doc\n2. Share → Anyone with link can EDIT\n3. Copy the URL\n4. !sync setup <url>"
    
    parts = args.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    
    if cmd == "setup":
        if len(parts) < 2:
            return "Usage: !sync setup <google-doc-url>\n\nMake sure the doc is set to 'Anyone with link can edit'!"
        
        doc_url = parts[1].strip()
        
        # Validate it's a Google Doc URL
        if "docs.google.com/document" not in doc_url:
            return "❌ Must be a Google Doc URL\n\nExample: https://docs.google.com/document/d/..."
        
        # Save config (we'll test permissions during first sync)
        state.sync_config.doc_url = doc_url
        state.sync_config.enabled = True
        state.save()
        
        logger.info("✅ Doc connected, doing initial sync...")
        
        # Trigger initial sync in background
        asyncio.create_task(test_and_sync_background(doc_url, message.chat_guid))
        
        return f"🔄 Connecting to Google Doc...\n\nTesting permissions and doing initial sync (~30 sec).\n\nI'll notify you when ready!"
    
    elif cmd == "now":
        if not state.sync_config.doc_url:
            return "No doc connected. Use: !sync setup <url>"
        
        logger.info("🔄 Manual sync requested...")
        state._trigger_sync()
        return f"🔄 Syncing to Google Doc...\n\nThis takes ~30 seconds. Check the doc in a moment!"
    
    elif cmd == "enable":
        if not state.sync_config.doc_url:
            return "No doc connected. Use: !sync setup <url> first"
        
        state.sync_config.enabled = True
        state.save()
        return "✅ Auto-sync enabled\n\nDoc will update automatically on changes."
    
    elif cmd == "disable":
        state.sync_config.enabled = False
        state.save()
        return "⏸️ Auto-sync disabled\n\nDoc is still connected. Use !sync now to manually sync."
    
    elif cmd == "status":
        # Show detailed status
        if not state.sync_config.doc_url:
            return "No Google Doc connected.\n\nUse !sync setup <url> to connect."
        
        from datetime import datetime
        
        status = "📊 Sync Status\n\n"
        status += f"Doc: {state.sync_config.doc_url}\n\n"
        status += f"Auto-sync: {'✅ Enabled' if state.sync_config.enabled else '❌ Disabled'}\n"
        
        if state.sync_config.last_sync_at:
            try:
                sync_dt = datetime.fromisoformat(state.sync_config.last_sync_at)
                time_str = sync_dt.strftime("%B %d at %I:%M %p")
                status += f"Last sync: {time_str}\n"
            except:
                status += f"Last sync: {state.sync_config.last_sync_at}\n"
        else:
            status += "Last sync: Never\n"
        
        status += f"Status: {state.sync_config.last_sync_status}\n\n"
        status += f"📊 Data to sync:\n"
        status += f"• Total items: {len(state.items)}\n"
        status += f"• Official items: {len([i for i in state.items if i.is_official])}\n"
        status += f"• Venues: {len(state.get_venues())}\n"
        status += f"• Flights: {len(state.get_flights())}\n"
        status += f"• Documents: {len(state.get_documents())}\n"
        
        return status
    
    else:
        return "Usage: !sync setup/now/enable/disable/status\n\nExamples:\n• !sync setup <url>\n• !sync now\n• !sync status"


@bot.on_message
@command("!help")
def help_command(message: Message):
    """Show available commands"""
    commands = [
        "🤖 Travel Planner Bot Commands:",
        "",
        "💬 Conversation:",
        "!track - Start tracking messages",
        "!track stop - Stop tracking",
        "!reset - Clear all indexed messages",
        "!ask [question] - Ask about trip details",
        "  Example: !ask what's the wifi password?",
        "",
        "🏠 Venues:",
        "!venue [criteria] - Search for accommodations",
        "  Example: !venue Lake Tahoe, 4 people, Aug 25-30",
        "💡 Tip: Just paste Airbnb/Vrbo/Google Doc links - auto-saved!",
        "",
        "📋 Items (venues, docs, flights):",
        "!list [filter] - List all items",
        "  Filters: venues, docs, official",
        "  Example: !list venues",
        "!show <number> - Show item details",
        "!comment <number> <text> - Add feedback",
        "!official <number> [number2]... - Mark as official",
        "  Example: !official 16 or !official 16 23 45",
        "!delete <number> - Delete an item",
        "",
        "📄 Documents (legacy):",
        "!docs - List documents",
        "!docs delete <number> - Delete document",
        "",
        "🎯 Trip Summary:",
        "!trip - Show all official items (accommodation, docs, etc.)",
        "",
        "✈️ Flights:",
        "!flight [criteria] - Search for flights",
        "  Example: !flight from SFO to RNO on Aug 25",
        "",
        "💰 Budget:",
        "!budget show - Show budget summary",
        "!budget set <amount> - Set total trip budget",
        "  Example: !budget set 5000",
        "!budget add [item] [amount] - Add expense",
        "  Example: !budget add airbnb 1500",
        "",
        "📄 Google Docs Sync:",
        "!sync setup <url> - Connect to a Google Doc",
        "!sync now - Force sync to doc",
        "!sync status - Show sync status",
        "!sync enable/disable - Toggle auto-sync",
        "💡 Tip: Set doc to 'Anyone with link can edit'!",
        "",
        "📊 Status:",
        "!status - Show current trip status",
        "!help - Show this help message"
    ]
    return "\n".join(commands)


@bot.on_message
@command("!status")
def status_command(message: Message):
    """Show current trip status"""
    if not state.trip:
        return "No active trip. Start planning by searching for venues or flights!"
    
    response = f"📍 {state.trip.name}\n"
    
    if state.trip.destination:
        response += f"Destination: {state.trip.destination}\n"
    
    if state.trip.dates.get("start") and state.trip.dates.get("end"):
        response += f"Dates: {state.trip.dates['start']} to {state.trip.dates['end']}\n"
    
    # Show tracking status
    tracking_status = "🟢 Active" if state.trip.is_tracking else "🔴 Inactive"
    response += f"\nTracking: {tracking_status}\n"
    
    # Count indexed messages
    try:
        count_result = collection.count()
        response += f"📝 Indexed messages: {count_result}\n"
    except:
        pass
    
    response += f"\n👥 Members: {len(state.members)}\n"
    response += f"🏠 Venues found: {len(state.get_venues())}\n"
    response += f"✈️ Flights found: {len(state.get_flights())}\n"
    
    # Show official docs
    official_docs = state.get_official_documents()
    if official_docs:
        response += f"\n⭐ Official Trip Docs:\n"
        for doc in official_docs:
            response += f"  • {doc.title} ({doc.doc_type})\n"
    
    response += f"\n📄 Total saved documents: {len(state.get_documents())}\n"
    
    # Show budget
    total_spent = state.get_total_spent()
    if state.trip and state.trip.total_budget:
        remaining = state.trip.total_budget - total_spent
        response += f"💰 Budget: ${total_spent:.2f} / ${state.trip.total_budget:,.2f} (${remaining:,.2f} left)\n"
    else:
        response += f"💰 Total spent: ${total_spent:.2f}\n"
    
    if not official_docs and state.get_documents():
        response += f"\n💡 Tip: Use !doc use <number> to mark official trip docs"
    
    return response


if __name__ == "__main__":
    print(f"🚀 Starting {BOT_NAME}...")
    print(f"💾 State file: {state.file_path}")
    print(f"🔍 Chroma DB: {CHROMA_PERSIST_DIRECTORY}")
    
    if state.trip and state.trip.is_tracking:
        print(f"📝 Currently tracking: {state.trip.tracked_conversation_id}")
    else:
        print(f"📝 Not tracking any conversation. Use !track to start.")
    
    print("\nAvailable commands: !help, !track, !ask, !venue, !doc, !docs, !trip, !flight, !checkin, !budget, !status")
    print("\n💡 Quick start:")
    print("  1. Send !track to start tracking messages")
    print("  2. Paste Airbnb/Vrbo/Google Doc links - they're auto-saved!")
    print("  3. Use !doc use 1 to mark official trip docs")
    print("  4. Ask questions with !ask what's the wifi password?")
    print("\nBot is running! Send messages to test it out.")
    bot.run()

