"""
Data models and state management for Travel Planner Bot
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import json
import os
from config import STATE_FILE_PATH


@dataclass
class SyncConfig:
    """Configuration for Google Doc sync"""
    enabled: bool = False
    doc_url: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_sync_status: str = "never"  # "success", "failed", "in_progress", "never"
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SyncConfig':
        return cls(**data)


@dataclass
class Item:
    """Base class for all referenceable items (venues, documents, flights)"""
    id: int = 0
    title: str = ""
    url: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = "system"
    comments: List[Dict] = field(default_factory=list)
    is_official: bool = False
    tags: List[str] = field(default_factory=list)
    
    @property
    def item_type(self) -> str:
        """Return the type of item (venue, document, flight)"""
        return self.__class__.__name__.lower()
    
    def add_comment(self, user: str, text: str):
        """Add a comment to this item"""
        self.comments.append({
            "user": user,
            "text": text,
            "timestamp": datetime.now().isoformat()
        })
    
    def to_dict(self) -> Dict:
        """Serialize to dict with type info for JSON storage"""
        return {"__type__": self.__class__.__name__, **asdict(self)}
    
    @classmethod
    def from_dict(cls, data: Dict):
        """Deserialize from dict"""
        data_copy = dict(data)
        data_copy.pop("__type__", None)
        # Only use fields that exist in this class
        valid_fields = {k: v for k, v in data_copy.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class FlightCriteria:
    """Flight criteria for a member"""
    departure: Optional[str] = None
    destination: Optional[str] = None
    arrival_date: Optional[str] = None
    departure_time: Optional[str] = None  # ISO format
    flight_number: Optional[str] = None
    confirmation_code: Optional[str] = None
    airline: Optional[str] = None
    last_name: Optional[str] = None

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict) -> 'FlightCriteria':
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class Member:
    """Trip member with preferences and flight info"""
    name: str
    location: Optional[str] = None
    budget: Optional[float] = None
    flight_criteria: FlightCriteria = field(default_factory=FlightCriteria)
    notes: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "location": self.location,
            "budget": self.budget,
            "flight_criteria": self.flight_criteria.to_dict(),
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Member':
        flight_criteria = FlightCriteria.from_dict(data.get("flight_criteria", {}))
        return cls(
            name=data["name"],
            location=data.get("location"),
            budget=data.get("budget"),
            flight_criteria=flight_criteria,
            notes=data.get("notes")
        )


@dataclass
class Trip:
    """Trip information"""
    name: str
    destination: Optional[str] = None
    dates: Dict[str, str] = field(default_factory=dict)  # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    is_tracking: bool = False
    tracked_conversation_id: Optional[str] = None  # The conversation being tracked
    total_budget: Optional[float] = None  # Total trip budget

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'Trip':
        return cls(**data)


@dataclass
class Venue(Item):
    """Venue (Airbnb/Vrbo listing) information"""
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    image_url: Optional[str] = None
    amenities: List[str] = field(default_factory=list)
    bedrooms: Optional[int] = None
    beds: Optional[int] = None
    source: str = "airbnb"  # "airbnb" or "vrbo"
    structured_data: Dict = field(default_factory=dict)  # For scraped details


@dataclass
class Flight(Item):
    """Flight option for a member"""
    member: str = ""
    route: str = ""  # "SFO->RNO"
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    departure_time: Optional[str] = None  # ISO format
    arrival_time: Optional[str] = None  # ISO format
    duration: Optional[str] = None
    stops: int = 0
    price: Optional[float] = None


@dataclass
class BudgetEntry:
    """Budget ledger entry"""
    item: str
    amount: float
    date: str  # ISO format
    paid_by: str
    notes: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'BudgetEntry':
        return cls(**data)


@dataclass
class Document(Item):
    """Saved document (Airbnb listing, Google Doc, etc.)"""
    doc_type: str = "html"  # "airbnb", "vrbo", "google_doc", "html"
    structured_data: Dict = field(default_factory=dict)  # Extracted fields


# Backward compatibility alias
SavedDocument = Document


class TravelState:
    """Main state manager for the travel bot"""
    
    def __init__(self, file_path: str = STATE_FILE_PATH):
        self.file_path = file_path
        self.trip: Optional[Trip] = None
        self.members: Dict[str, Member] = {}
        self.items: List[Union[Venue, Document, Flight]] = []
        self.next_item_id: int = 1
        self.budget_ledger: List[BudgetEntry] = []
        self.venue_pagination_index: int = 0  # For !venue next
        self.sync_config: SyncConfig = SyncConfig()
        
        # Sync state (not persisted)
        self._sync_lock = None  # Will be initialized as asyncio.Lock() when needed
        self._pending_sync: bool = False
        
        # Load existing state
        self.load()

    def load(self):
        """Load state from JSON file"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                
                # Load trip
                if "trip" in data and data["trip"]:
                    self.trip = Trip.from_dict(data["trip"])
                
                # Load members
                self.members = {
                    name: Member.from_dict({**member_data, "name": name})
                    for name, member_data in data.get("members", {}).items()
                }
                
                # Load budget
                self.budget_ledger = [BudgetEntry.from_dict(e) for e in data.get("budget_ledger", [])]
                
                # Load items with type awareness
                type_map = {"Venue": Venue, "Document": Document, "Flight": Flight}
                self.items = []
                
                for item_dict in data.get("items", []):
                    item_type = item_dict.get("__type__", "Item")
                    cls = type_map.get(item_type, Item)
                    self.items.append(cls.from_dict(item_dict))
                
                self.next_item_id = data.get("next_item_id", 1)
                self.venue_pagination_index = data.get("venue_pagination_index", 0)
                
                # Load sync config
                if "sync_config" in data:
                    self.sync_config = SyncConfig.from_dict(data["sync_config"])
                
            except Exception as e:
                print(f"Error loading state: {e}")
                import traceback
                traceback.print_exc()
                self._initialize_default_state()
        else:
            self._initialize_default_state()
    
    def _initialize_default_state(self):
        """Initialize with default empty state"""
        self.trip = Trip(name="New Trip", is_tracking=False)
        self.members = {}
        self.items = []
        self.next_item_id = 1
        self.venue_pagination_index = 0
        self.budget_ledger = []

    def save(self):
        """Save state to JSON file"""
        try:
            data = {
                "trip": self.trip.to_dict() if self.trip else None,
                "members": {name: member.to_dict() for name, member in self.members.items()},
                "items": [item.to_dict() for item in self.items],
                "next_item_id": self.next_item_id,
                "venue_pagination_index": self.venue_pagination_index,
                "budget_ledger": [e.to_dict() for e in self.budget_ledger],
                "sync_config": self.sync_config.to_dict()
            }
            
            with open(self.file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}")

    def get_or_create_member(self, name: str) -> Member:
        """Get existing member or create new one"""
        if name not in self.members:
            self.members[name] = Member(name=name)
            self.save()
        return self.members[name]
    
    # New Item-based methods
    def get_venues(self) -> List[Venue]:
        """Get all venue items"""
        return [i for i in self.items if isinstance(i, Venue)]
    
    def get_documents(self) -> List[Document]:
        """Get all document items"""
        return [i for i in self.items if isinstance(i, Document)]
    
    def get_flights(self) -> List[Flight]:
        """Get all flight items"""
        return [i for i in self.items if isinstance(i, Flight)]
    
    def get_item_by_id(self, item_id: int) -> Optional[Union[Venue, Document, Flight]]:
        """Get item by its ID"""
        return next((i for i in self.items if i.id == item_id), None)
    
    def add_item(self, item: Union[Venue, Document, Flight]) -> Union[Venue, Document, Flight]:
        """Add an item and auto-assign ID"""
        item.id = self.next_item_id
        self.next_item_id += 1
        self.items.append(item)
        self.save()
        self._trigger_sync()
        return item
    
    def delete_item(self, item_id: int) -> bool:
        """Delete an item by ID"""
        item = self.get_item_by_id(item_id)
        if item:
            self.items.remove(item)
            self.save()
            self._trigger_sync()
            return True
        return False
    
    # Legacy methods for backward compatibility (redirect to add_item)
    def add_venue(self, venue: Venue):
        """Add a venue (legacy method, use add_item instead)"""
        self.add_item(venue)

    def add_flight(self, flight: Flight):
        """Add a flight (legacy method, use add_item instead)"""
        self.add_item(flight)

    def add_budget_entry(self, entry: BudgetEntry):
        """Add a budget entry"""
        self.budget_ledger.append(entry)
        self.save()
        self._trigger_sync()

    def get_total_budget(self) -> float:
        """Calculate total budget across all members"""
        return sum(m.budget or 0 for m in self.members.values())

    def get_total_spent(self) -> float:
        """Calculate total amount spent"""
        return sum(e.amount for e in self.budget_ledger)

    def clear_venues(self):
        """Clear all venues"""
        self.items = [i for i in self.items if not isinstance(i, Venue)]
        self.save()

    def clear_flights(self):
        """Clear all flights"""
        self.items = [i for i in self.items if not isinstance(i, Flight)]
        self.save()
    
    def add_saved_document(self, doc: Document):
        """Add a saved document (legacy method, use add_item instead)"""
        self.add_item(doc)
    
    def clear_saved_documents(self):
        """Clear all saved documents"""
        self.items = [i for i in self.items if not isinstance(i, Document)]
        self.save()
    
    def mark_document_as_official(self, doc_id: int):
        """Mark a document as official (representing the actual trip)"""
        # Find the document
        doc = self.get_item_by_id(doc_id)
        if not doc or not isinstance(doc, Document):
            return False
        
        # If it's airbnb or vrbo, unmark any other airbnb/vrbo
        if doc.doc_type in ["airbnb", "vrbo"]:
            for item in self.items:
                if isinstance(item, Document) and item.doc_type in ["airbnb", "vrbo"] and item.id != doc_id:
                    item.is_official = False
        
        # Mark this one as official
        doc.is_official = True
        self.save()
        self._trigger_sync()
        return True
    
    def mark_item_as_official(self, item_id: int):
        """Mark any item as official"""
        item = self.get_item_by_id(item_id)
        if not item:
            return False
        
        item.is_official = True
        self.save()
        self._trigger_sync()
        return True
    
    def get_official_documents(self) -> List[Document]:
        """Get all official documents"""
        return [item for item in self.items if isinstance(item, Document) and item.is_official]
    
    def _trigger_sync(self):
        """Trigger a Google Doc sync if enabled"""
        if not self.sync_config.enabled or not self.sync_config.doc_url:
            return
        
        self._pending_sync = True
        
        # Schedule async sync in background (don't wait for it)
        import asyncio
        try:
            # Try to create task in existing event loop
            loop = asyncio.get_running_loop()
            loop.create_task(self._run_sync())
        except RuntimeError:
            # No event loop running, create one for this task
            asyncio.create_task(self._run_sync())
    
    async def _run_sync(self):
        """Run sync with lock to prevent concurrent syncs"""
        import asyncio
        
        # Initialize lock if needed (can't be done in __init__ due to event loop issues)
        if self._sync_lock is None:
            self._sync_lock = asyncio.Lock()
        
        # Try to acquire lock (non-blocking)
        if self._sync_lock.locked():
            print("⏭️  Sync already in progress, skipping duplicate")
            return
        
        async with self._sync_lock:
            if not self._pending_sync:
                return
            
            self._pending_sync = False
            print("🔄 Starting Google Doc sync...")
            
            try:
                # Import here to avoid circular dependency
                from google_doc_sync import sync_to_google_doc
                success = await sync_to_google_doc(self)
                
                if success:
                    print("✅ Google Doc synced successfully")
                else:
                    print("❌ Google Doc sync failed")
            except Exception as e:
                print(f"❌ Sync error: {e}")
                import traceback
                traceback.print_exc()

