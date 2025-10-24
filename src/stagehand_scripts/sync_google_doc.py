"""
Google Doc sync using Stagehand and Browserbase

Reads the current doc, uses AI to generate smart edits, and applies them
"""

import os
import sys
import json
import asyncio
from typing import Dict, Optional
from datetime import datetime
from stagehand import Stagehand, StagehandConfig
from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def sync_google_doc(doc_url: str, trip_data: Dict) -> Dict:
    """
    Sync trip data to Google Doc intelligently
    
    Args:
        doc_url: Google Doc URL (must be publicly editable)
        trip_data: Trip data from prepare_trip_data()
    
    Returns:
        {"success": bool, "error": Optional[str]}
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
        print("🚀 Initializing Stagehand for Google Doc sync...")
        await stagehand.init()
        page = stagehand.page
        print("✅ Stagehand initialized")
        
        # Navigate to doc
        print(f"🌐 Navigating to: {doc_url}")
        await page.goto(doc_url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(3000)
        print("✅ Page loaded")
        
        # Check if we can edit
        print("🔍 Checking edit permissions...")
        can_edit = await check_edit_permissions(page)
        
        if not can_edit:
            return {
                "success": False,
                "error": "Cannot edit document. Please set to 'Anyone with link can edit' in Share settings."
            }
        
        print("✅ Edit permissions confirmed")
        
        # Read current doc content
        print("📖 Reading current document...")
        current_doc_text = await read_doc_content(page)
        print(f"✅ Read {len(current_doc_text)} characters from doc")
        
        # Generate new content using AI
        print("🤖 Generating updated document content with AI...")
        new_content = generate_doc_content(trip_data, current_doc_text)
        print(f"✅ Generated {len(new_content)} characters of new content")
        
        # Apply the update
        print("✏️  Applying updates to document...")
        await update_doc_content(page, new_content)
        print("✅ Document updated successfully")
        
        return {"success": True}
        
    except Exception as e:
        print(f"❌ Error syncing doc: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if page is not None:
            await stagehand.close()
            print("🧹 Browserbase session closed")


async def check_edit_permissions(page) -> bool:
    """Check if we can edit the document"""
    try:
        # First check if we can see the editor - this is the most reliable test
        has_editor = await page.evaluate("""
            () => {
                // Check for multiple possible editor elements
                const pageColumn = document.querySelector('.kix-page-column');
                const paginated = document.querySelector('.kix-page-paginated');
                const canvas = document.querySelector('.kix-canvas-tile-content');
                return pageColumn !== null || paginated !== null || canvas !== null;
            }
        """)
        
        if has_editor:
            print("✅ Document editor detected")
            return True
        
        # If no editor, then check for specific permission error messages
        print("⚠️ No editor found, checking for permission errors...")
        text_content = await page.evaluate("""
            () => document.body.innerText
        """)
        
        # Common permission error messages
        permission_errors = [
            "Request edit access",
            "You need permission",
            "Access denied",
            "You need access"
        ]
        
        for error_msg in permission_errors:
            if error_msg.lower() in text_content.lower():
                print(f"❌ Permission issue detected: '{error_msg}'")
                return False
        
        # No editor found and no clear error message
        print("❌ Document editor not found (unknown reason)")
        return False
        
    except Exception as e:
        print(f"Error checking permissions: {e}")
        return False


async def read_doc_content(page) -> str:
    """Read the current content of the Google Doc"""
    try:
        # Extract text from the Google Docs editor
        doc_text = await page.evaluate("""
            () => {
                const editor = document.querySelector('.kix-page-column');
                if (!editor) return '';
                
                // Get all paragraphs
                const paragraphs = editor.querySelectorAll('.kix-paragraphrenderer');
                const lines = Array.from(paragraphs).map(p => p.innerText);
                return lines.join('\\n');
            }
        """)
        
        return doc_text or ""
        
    except Exception as e:
        print(f"Error reading doc: {e}")
        return ""


def generate_doc_content(trip_data: Dict, current_doc: str) -> str:
    """
    Use OpenAI to generate updated document content
    
    Reads the current doc and trip data, generates new content that:
    1. Preserves the required structure
    2. Updates with latest trip data
    3. Preserves user-added custom sections
    """
    trip = trip_data["trip"]
    trip_name = trip.get("name", "Trip")
    dates = trip.get("dates", {})
    date_range = f"{dates.get('start', 'TBD')} - {dates.get('end', 'TBD')}" if dates else "Dates TBD"
    
    # Build official accommodation section
    official_venues = trip_data.get("official_venues", [])
    official_docs = trip_data.get("official_docs", [])
    
    accommodation_section = "## 🏠 Accommodation\n\n"
    if official_venues:
        for venue in official_venues:
            accommodation_section += format_venue_section(venue)
    elif [d for d in official_docs if d.get("doc_type") in ["airbnb", "vrbo"]]:
        for doc in official_docs:
            if doc.get("doc_type") in ["airbnb", "vrbo"]:
                accommodation_section += format_document_section(doc)
    else:
        accommodation_section += "Not selected yet. Use !list venues in the bot to see options.\n\n"
    
    # Build flights section
    flights_section = "## ✈️ Flights\n\n"
    all_flights = trip_data.get("all_flights", [])
    if all_flights:
        # Group by member
        flights_by_member = {}
        for flight in all_flights:
            member = flight.get("member", "Unknown")
            if member not in flights_by_member:
                flights_by_member[member] = []
            flights_by_member[member].append(flight)
        
        for member, flights in flights_by_member.items():
            flights_section += f"**{member}**\n"
            for flight in flights:
                flights_section += f"- {flight.get('title', 'Flight')} (Item #{flight.get('id')})\n"
                if flight.get('price'):
                    flights_section += f"  💰 ${flight['price']}\n"
                if flight.get('url'):
                    flights_section += f"  🔗 {flight['url']}\n"
            flights_section += "\n"
    else:
        flights_section += "No flights booked yet. Use !flight in the bot to search.\n\n"
    
    # Build budget section
    budget_section = "## 💰 Budget\n\n"
    budget = trip_data.get("budget", {})
    total_budget = budget.get("total_budget")
    total_spent = budget.get("total_spent", 0)
    
    if total_budget:
        remaining = total_budget - total_spent
        budget_section += f"**Total Budget:** ${total_budget:,.2f}\n"
        budget_section += f"**Total Spent:** ${total_spent:,.2f}\n"
        budget_section += f"**Remaining:** ${remaining:,.2f}\n\n"
    else:
        budget_section += f"**Total Spent:** ${total_spent:,.2f}\n"
        budget_section += "💡 Set budget with !budget set <amount> in bot\n\n"
    
    # Breakdown
    if budget.get("entries"):
        budget_section += "**Breakdown:**\n"
        for entry in budget["entries"]:
            budget_section += f"- {entry['item']}: ${entry['amount']:.2f} ({entry['paid_by']})\n"
        budget_section += "\n"
    
    # Build all items section
    items_section = "## 📋 All Items\n\n"
    stats = trip_data.get("stats", {})
    items_section += f"Total: {stats.get('total_items', 0)} items ({stats.get('venues_count', 0)} venues, {stats.get('flights_count', 0)} flights, {stats.get('docs_count', 0)} docs)\n\n"
    
    all_venues = trip_data.get("all_venues", [])
    if all_venues:
        items_section += "**Top Venues:**\n"
        for venue in all_venues:
            official_mark = " ⭐" if venue.get("is_official") else ""
            price_info = f" - ${venue.get('price_per_night')}/night" if venue.get('price_per_night') else ""
            rating_info = f" ⭐ {venue.get('rating')}" if venue.get('rating') else ""
            items_section += f"{venue.get('id')}. {venue.get('title')}{price_info}{rating_info}{official_mark}\n"
        items_section += "\n"
    
    items_section += "💡 Use !list in bot to see all items\n\n"
    
    # Build comments section
    comments_section = "## 💬 Recent Comments\n\n"
    recent_comments = trip_data.get("recent_comments", [])
    if recent_comments:
        for comment in recent_comments[:10]:  # Top 10
            comments_section += f"• **{comment['user']}** on Item #{comment['item_id']} ({comment['item_title']}): \"{comment['text']}\"\n"
        comments_section += "\n"
    else:
        comments_section += "No comments yet. Use !comment <number> <text> in the bot.\n\n"
    
    # Build quick links section
    quick_links = """## 🔗 Quick Links

Bot Commands:
- !list - See all items
- !show <number> - View item details
- !comment <number> <text> - Add feedback
- !official <number> - Mark as official
- !ask <question> - Query trip data

Use the travel bot in iMessage for full trip management!
"""
    
    # Generate full document using OpenAI to handle smart merging
    prompt = f"""You are updating a Google Doc for a trip planning bot.

CURRENT DOCUMENT CONTENT:
{current_doc if current_doc else "[Empty document]"}

NEW TRIP DATA TO SYNC:

# 🎯 {trip_name} - {date_range}
Last synced: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}

{accommodation_section}

{flights_section}

{budget_section}

{items_section}

{comments_section}

{quick_links}

INSTRUCTIONS:
1. If the document is empty or doesn't have the structure above, create it from scratch using the NEW TRIP DATA exactly as shown.
2. If the document has content:
   - Keep any custom sections the user added (preserve them!)
   - Update the standard sections (Accommodation, Flights, Budget, All Items, Recent Comments) with new data
   - Update the "Last synced" timestamp
   - Maintain document formatting and structure
3. Return ONLY the complete document text that should replace the current content
4. Do not include any explanations or JSON - just the document text

OUTPUT THE COMPLETE DOCUMENT TEXT:"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that updates Google Docs for trip planning. You preserve user customizations while updating data."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        new_content = response.choices[0].message.content.strip()
        return new_content
        
    except Exception as e:
        print(f"Error generating doc content with AI: {e}")
        # Fallback: use the template directly
        return f"""# 🎯 {trip_name} - {date_range}
Last synced: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}

{accommodation_section}

{flights_section}

{budget_section}

{items_section}

{comments_section}

{quick_links}"""


def format_venue_section(venue: Dict) -> str:
    """Format a venue for the accommodation section"""
    section = f"**{venue.get('title', 'Unknown Venue')}** (Item #{venue.get('id')}) ⭐ OFFICIAL\n"
    section += f"- Source: {venue.get('source', 'unknown').capitalize()}\n"
    
    if venue.get('price_per_night'):
        section += f"- Price: ${venue['price_per_night']}/night"
        if venue.get('total_price'):
            section += f" (${venue['total_price']:.0f} total)"
        section += "\n"
    
    if venue.get('rating'):
        section += f"- Rating: ⭐ {venue['rating']}/5"
        if venue.get('review_count'):
            section += f" ({venue['review_count']} reviews)"
        section += "\n"
    
    if venue.get('bedrooms') or venue.get('beds'):
        section += f"- "
        if venue.get('bedrooms'):
            section += f"Bedrooms: {venue['bedrooms']}"
        if venue.get('beds'):
            section += f" | Beds: {venue['beds']}"
        section += "\n"
    
    if venue.get('url'):
        section += f"- URL: {venue['url']}\n"
    
    # Structured data if available
    if venue.get('structured_data'):
        data = venue['structured_data']
        if data.get('address'):
            section += f"\n📍 {data['address']}\n"
        if data.get('checkInTime'):
            section += f"🕐 Check-in: {data['checkInTime']}"
            if data.get('checkOutTime'):
                section += f" | Check-out: {data['checkOutTime']}"
            section += "\n"
        if data.get('wifiNetwork'):
            section += f"📶 WiFi: {data['wifiNetwork']}"
            if data.get('wifiPassword'):
                section += f" / {data['wifiPassword']}"
            section += "\n"
        if data.get('accessCodes'):
            section += "🔑 Access codes:\n"
            for code in data['accessCodes']:
                section += f"  • {code.get('name')}: {code.get('code')}\n"
    
    # Comments
    if venue.get('comments'):
        section += "\n**Comments:**\n"
        for comment in venue['comments']:
            section += f"• {comment['user']}: \"{comment['text']}\"\n"
    
    section += "\n"
    return section


def format_document_section(doc: Dict) -> str:
    """Format a document for the accommodation section"""
    section = f"**{doc.get('title', 'Unknown Document')}** (Item #{doc.get('id')}) ⭐ OFFICIAL\n"
    section += f"- Type: {doc.get('doc_type', 'document').replace('_', ' ').title()}\n"
    section += f"- URL: {doc.get('url', 'No URL')}\n"
    
    # Structured data
    if doc.get('structured_data'):
        data = doc['structured_data']
        if data.get('address'):
            section += f"\n📍 {data['address']}\n"
        if data.get('checkInTime'):
            section += f"🕐 Check-in: {data['checkInTime']}"
            if data.get('checkOutTime'):
                section += f" | Check-out: {data['checkOutTime']}"
            section += "\n"
        if data.get('wifiNetwork'):
            section += f"📶 WiFi: {data['wifiNetwork']}"
            if data.get('wifiPassword'):
                section += f" / {data['wifiPassword']}"
            section += "\n"
        if data.get('phoneNumber'):
            section += f"📞 {data['phoneNumber']}\n"
        if data.get('accessCodes'):
            section += "🔑 Access codes:\n"
            for code in data['accessCodes']:
                section += f"  • {code.get('name')}: {code.get('code')}\n"
    
    # Comments
    if doc.get('comments'):
        section += "\n**Comments:**\n"
        for comment in doc['comments']:
            section += f"• {comment['user']}: \"{comment['text']}\"\n"
    
    section += "\n"
    return section


async def make_targeted_edit(page, section_heading: str, new_section_content: str) -> bool:
    """
    Make a targeted edit to a specific section without clearing the whole doc
    
    Args:
        page: Playwright page object
        section_heading: The heading to find (e.g., "## 🏠 Accommodation")
        new_section_content: The new content for that section
    
    Returns:
        True if edit succeeded, False otherwise
    """
    try:
        print(f"🎯 Making targeted edit to section: {section_heading}")
        
        # Use Stagehand's act to find and update the section
        await page.act(f"Find the section with heading '{section_heading}' and select all its content (not the heading)")
        await page.wait_for_timeout(500)
        
        # Delete the selected content
        await page.keyboard.press('Backspace')
        await page.wait_for_timeout(300)
        
        # Type new content
        await page.keyboard.type(new_section_content, delay=10)
        await page.wait_for_timeout(500)
        
        print(f"✅ Targeted edit completed for: {section_heading}")
        return True
        
    except Exception as e:
        print(f"❌ Targeted edit failed: {e}")
        return False


async def update_doc_content(page, new_content: str) -> bool:
    """
    Replace the document content with new content
    
    Uses Stagehand AI to intelligently update the doc
    """
    try:
        # Step 1: Focus the editor with verification - try multiple strategies
        print("🎯 Focusing editor...")
        editor_focused = False
        
        # Define multiple focus strategies to try
        focus_strategies = [
            ("Click canvas center", "canvas"),
            ("Click paginated element", "paginated"),
            ("Click page column", "column"),
            ("Press Tab key", "tab"),
            ("Click canvas again", "canvas"),
            ("Press Tab twice", "tab_tab"),
            ("JavaScript focus", "js_focus"),
            ("Click and Tab", "click_tab"),
        ]
        
        for attempt, (strategy_name, strategy_type) in enumerate(focus_strategies):
            print(f"🔄 Trying: {strategy_name} (attempt {attempt + 1})")
            
            try:
                if strategy_type == "canvas":
                    editor = await page.query_selector('canvas.kix-canvas-tile-content')
                    if editor:
                        box = await editor.bounding_box()
                        if box:
                            await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            await page.wait_for_timeout(500)
                
                elif strategy_type == "paginated":
                    editor = await page.query_selector('.kix-page-paginated')
                    if editor:
                        box = await editor.bounding_box()
                        if box:
                            await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            await page.wait_for_timeout(500)
                
                elif strategy_type == "column":
                    editor = await page.query_selector('.kix-page-column')
                    if editor:
                        box = await editor.bounding_box()
                        if box:
                            await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            await page.wait_for_timeout(500)
                
                elif strategy_type == "tab":
                    await page.keyboard.press('Tab')
                    await page.wait_for_timeout(500)
                
                elif strategy_type == "tab_tab":
                    await page.keyboard.press('Tab')
                    await page.wait_for_timeout(300)
                    await page.keyboard.press('Tab')
                    await page.wait_for_timeout(500)
                
                elif strategy_type == "js_focus":
                    await page.evaluate("""
                        () => {
                            const canvas = document.querySelector('canvas.kix-canvas-tile-content');
                            if (canvas) canvas.focus();
                        }
                    """)
                    await page.wait_for_timeout(500)
                
                elif strategy_type == "click_tab":
                    editor = await page.query_selector('canvas.kix-canvas-tile-content')
                    if editor:
                        box = await editor.bounding_box()
                        if box:
                            await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            await page.wait_for_timeout(300)
                    await page.keyboard.press('Tab')
                    await page.wait_for_timeout(500)
                
                # Verify focus
                test_focused = await page.evaluate("""
                    () => {
                        const activeElement = document.activeElement;
                        return activeElement && activeElement.tagName !== 'BODY';
                    }
                """)
                
                if test_focused:
                    print(f"✅ Editor focused using: {strategy_name}")
                    editor_focused = True
                    break
                
            except Exception as e:
                print(f"⚠️ Strategy '{strategy_name}' failed: {e}")
        
        if not editor_focused:
            print("❌ Could not focus editor after trying all strategies")
            return False
        
        # Step 2: Clear content with verification - try multiple methods
        print("🗑️ Clearing document content...")
        content_cleared = False
        
        clear_strategies = [
            ("Cmd+A then Backspace", "cmd_a_backspace"),
            ("Cmd+A then Delete", "cmd_a_delete"),
            ("Triple Cmd+A then Backspace", "triple_cmd_a"),
        ]
        
        for strategy_name, strategy_type in clear_strategies:
            if content_cleared:
                break
                
            for attempt in range(2):
                print(f"🔄 Trying: {strategy_name} (attempt {attempt + 1})")
                
                if strategy_type == "cmd_a_backspace":
                    await page.keyboard.down('Meta')
                    await page.keyboard.press('a')
                    await page.keyboard.up('Meta')
                    await page.wait_for_timeout(300)
                    await page.keyboard.press('Backspace')
                    await page.wait_for_timeout(1000)
                
                elif strategy_type == "cmd_a_delete":
                    await page.keyboard.down('Meta')
                    await page.keyboard.press('a')
                    await page.keyboard.up('Meta')
                    await page.wait_for_timeout(300)
                    await page.keyboard.press('Delete')
                    await page.wait_for_timeout(1000)
                
                elif strategy_type == "triple_cmd_a":
                    # Sometimes need to select multiple times for nested content
                    for _ in range(3):
                        await page.keyboard.down('Meta')
                        await page.keyboard.press('a')
                        await page.keyboard.up('Meta')
                        await page.wait_for_timeout(200)
                    await page.keyboard.press('Backspace')
                    await page.wait_for_timeout(1000)
                
                # Verify content is cleared
                current_text = await page.evaluate("""
                    () => {
                        const editor = document.querySelector('.kix-page-column');
                        if (!editor) return null;
                        const paragraphs = editor.querySelectorAll('.kix-paragraphrenderer');
                        const text = Array.from(paragraphs).map(p => p.innerText).join('');
                        return text.trim();
                    }
                """)
                
                if current_text is not None and len(current_text) <= 1:
                    print(f"✅ Content cleared using: {strategy_name}")
                    content_cleared = True
                    break
                else:
                    print(f"⚠️ {len(current_text) if current_text else 'unknown'} chars remaining")
        
        if not content_cleared:
            print("❌ Could not clear content after trying all strategies")
            return False
        
        # Step 3: Type new content - sentence by sentence for speed
        print("✍️  Writing new content...")
        
        # Split into sentences/paragraphs for faster typing
        # Group by double newlines (paragraphs) and single newlines (lines)
        paragraphs = new_content.split('\n\n')
        total_paragraphs = len(paragraphs)
        
        for para_idx, paragraph in enumerate(paragraphs):
            lines = paragraph.split('\n')
            
            for line_idx, line in enumerate(lines):
                if line.strip():  # Skip empty lines
                    # Type entire line at once (much faster than char by char)
                    await page.keyboard.type(line, delay=10)  # 10ms delay between chars
                
                # Press Enter if not the last line in paragraph
                if line_idx < len(lines) - 1:
                    await page.keyboard.press('Enter')
            
            # Double Enter for paragraph break (if not last paragraph)
            if para_idx < total_paragraphs - 1:
                await page.keyboard.press('Enter')
                await page.keyboard.press('Enter')
            
            # Progress indicator every 5 paragraphs
            if (para_idx + 1) % 5 == 0:
                print(f"  📝 Progress: {para_idx + 1}/{total_paragraphs} paragraphs")
                await page.wait_for_timeout(100)  # Brief pause to let editor catch up
        
        print("✅ Content written successfully")
        await page.wait_for_timeout(2000)  # Let doc save
        
        return True
        
    except Exception as e:
        print(f"Error updating doc content: {e}")
        return False


async def main():
    """Main execution when run as script"""
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "Missing required argument: doc_url"
        }))
        sys.exit(1)
    
    doc_url = sys.argv[1]
    
    # Simple test data
    trip_data = {
        "trip": {"name": "Test Trip", "dates": {}},
        "official_venues": [],
        "official_docs": [],
        "all_venues": [],
        "all_flights": [],
        "all_docs": [],
        "recent_comments": [],
        "budget": {},
        "stats": {}
    }
    
    result = await sync_google_doc(doc_url, trip_data)
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())

