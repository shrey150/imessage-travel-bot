"""
Google Doc sync orchestration

Coordinates reading current doc state, generating updates, and applying them
"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from models import TravelState, Venue, Document, Flight


async def sync_to_google_doc(state: TravelState) -> bool:
    """
    Intelligently sync state to Google Doc
    
    Args:
        state: Current travel state
    
    Returns:
        True if sync succeeded, False otherwise
    """
    doc_url = state.sync_config.doc_url
    
    if not doc_url:
        print("❌ No doc URL configured")
        return False
    
    try:
        # Update status
        state.sync_config.last_sync_status = "in_progress"
        state.save()
        
        # Import the sync script
        from stagehand_scripts.sync_google_doc import sync_google_doc
        
        # Prepare trip data
        trip_data = prepare_trip_data(state)
        
        # Run the sync
        result = await sync_google_doc(doc_url, trip_data)
        
        # Update sync status
        state.sync_config.last_sync_at = datetime.now().isoformat()
        
        if result.get("success"):
            state.sync_config.last_sync_status = "success"
            state.save()
            return True
        else:
            state.sync_config.last_sync_status = "failed"
            state.save()
            print(f"❌ Sync failed: {result.get('error')}")
            return False
            
    except Exception as e:
        state.sync_config.last_sync_status = "failed"
        state.save()
        print(f"❌ Sync exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def prepare_trip_data(state: TravelState) -> Dict[str, Any]:
    """
    Prepare trip data in a format ready for doc sync
    
    Returns:
        Dict with all trip information formatted for the doc
    """
    # Get official items
    official_items = [i for i in state.items if i.is_official]
    official_venues = [i for i in official_items if isinstance(i, Venue)]
    official_docs = [i for i in official_items if isinstance(i, Document)]
    
    # Get all items by type
    all_venues = state.get_venues()
    all_flights = state.get_flights()
    all_docs = state.get_documents()
    
    # Get recent comments (last 20 across all items)
    all_comments = []
    for item in state.items:
        for comment in item.comments:
            all_comments.append({
                "item_id": item.id,
                "item_title": item.title,
                "user": comment["user"],
                "text": comment["text"],
                "timestamp": comment["timestamp"]
            })
    
    # Sort by timestamp (most recent first)
    all_comments.sort(key=lambda c: c["timestamp"], reverse=True)
    recent_comments = all_comments[:20]
    
    # Budget info
    total_budget = state.trip.total_budget if state.trip else None
    total_spent = state.get_total_spent()
    budget_entries = [e.to_dict() for e in state.budget_ledger]
    
    # Trip info
    trip_info = state.trip.to_dict() if state.trip else {
        "name": "New Trip",
        "destination": "TBD",
        "dates": {}
    }
    
    return {
        "trip": trip_info,
        "official_venues": [v.to_dict() for v in official_venues],
        "official_docs": [d.to_dict() for d in official_docs],
        "all_venues": [v.to_dict() for v in all_venues[:10]],  # Top 10
        "all_flights": [f.to_dict() for f in all_flights],
        "all_docs": [d.to_dict() for d in all_docs],
        "recent_comments": recent_comments,
        "budget": {
            "total_budget": total_budget,
            "total_spent": total_spent,
            "entries": budget_entries
        },
        "stats": {
            "total_items": len(state.items),
            "venues_count": len(all_venues),
            "flights_count": len(all_flights),
            "docs_count": len(all_docs),
            "official_count": len(official_items)
        }
    }

