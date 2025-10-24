"""
OpenAI helpers for criteria extraction, Q&A, and intelligent responses
"""

from typing import Dict, List, Optional, Any
import json
from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def extract_venue_criteria(user_message: str, trip_context: Dict) -> Dict:
    """
    Extract venue search criteria from user message using OpenAI
    
    Returns:
        Dict with keys: destination, checkin, checkout, adults, children, budget, needs_clarification, clarification_question
    """
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year
    
    system_prompt = f"""You are a helpful travel planning assistant. Extract venue search criteria from the user's message.

TODAY'S DATE: {current_date}
CURRENT YEAR: {current_year}

When parsing dates:
- If year is not specified, assume the CURRENT year ({current_year}) or next year if the date has passed
- Convert relative dates (e.g., "next week", "nov 21") to YYYY-MM-DD format
- For month-only dates like "nov 21-23", use the current year if November hasn't passed, otherwise next year
    
Current trip context: {json.dumps(trip_context, indent=2)}

Extract and return JSON with these fields:
- destination (string): Where they want to stay
- checkin (string): Check-in date in YYYY-MM-DD format
- checkout (string): Check-out date in YYYY-MM-DD format  
- adults (number): Number of adults
- children (number): Number of children
- budget (number): Maximum budget per night or total
- needs_clarification (boolean): True if critical info is missing
- clarification_question (string): Question to ask if needs_clarification is true

If information can be inferred from trip context, use it. Only ask for clarification if truly necessary."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"Error extracting venue criteria: {e}")
        return {
            "needs_clarification": True,
            "clarification_question": "Could you tell me where you want to stay, check-in/out dates, and how many people?"
        }


def extract_flight_criteria(user_message: str, member_name: str, trip_context: Dict, member_context: Dict) -> Dict:
    """
    Extract flight search criteria from user message using OpenAI
    
    Returns:
        Dict with keys: origin, destination, departure_date, return_date, budget, needs_clarification, clarification_question
    """
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year
    
    system_prompt = f"""You are a helpful travel planning assistant. Extract flight search criteria for {member_name}.

TODAY'S DATE: {current_date}
CURRENT YEAR: {current_year}

When parsing dates:
- If year is not specified, assume the CURRENT year ({current_year}) or next year if the date has passed
- Convert relative dates to YYYY-MM-DD format
- For month-only dates, use the current year if that month hasn't passed, otherwise next year
    
Current trip context: {json.dumps(trip_context, indent=2)}
Member context: {json.dumps(member_context, indent=2)}

Extract and return JSON with these fields:
- origin (string): Departure airport code or city
- destination (string): Arrival airport code or city
- departure_date (string): Date in YYYY-MM-DD format
- return_date (string): Return date in YYYY-MM-DD format (if round trip)
- budget (number): Maximum price willing to pay
- needs_clarification (boolean): True if critical info is missing
- clarification_question (string): Question to ask if needs_clarification is true

Use trip and member context to fill in defaults when possible."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"Error extracting flight criteria: {e}")
        return {
            "needs_clarification": True,
            "clarification_question": f"Could you tell me where {member_name} is flying from, when, and what's the budget?"
        }


def answer_question_with_context(question: str, relevant_messages: List[Dict], state_context: Dict) -> str:
    """
    Answer a question using relevant conversation messages and current state
    
    Args:
        question: The user's question
        relevant_messages: List of relevant messages from Chroma search
        state_context: Current trip state (venues, flights, budget, etc.)
    
    Returns:
        Answer string
    """
    # Format messages for context
    messages_text = "\n".join([
        f"[{msg.get('timestamp', 'unknown')}] {msg.get('sender', 'unknown')}: {msg.get('text', '')}"
        for msg in relevant_messages
    ])
    
    system_prompt = f"""You are a helpful travel planning assistant. Answer the user's question using the conversation history and current trip state.
    
Conversation history:
{messages_text}

Current trip state:
{json.dumps(state_context, indent=2)}

Provide a clear, concise answer. If information is missing, let the user know and suggest how they can provide it."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.5
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error answering question: {e}")
        return "Sorry, I had trouble processing that question. Could you try rephrasing it?"


def parse_budget_command(user_message: str) -> Dict:
    """
    Parse budget command to extract action and details
    
    Returns:
        Dict with keys: action (show/add), item, amount, notes
    """
    system_prompt = """Parse the budget command and return JSON with:
- action (string): "show" or "add"
- item (string): Description of expense (for add action)
- amount (number): Amount in dollars (for add action)
- notes (string): Additional notes

Examples:
"!budget show" -> {"action": "show"}
"!budget add airbnb $500" -> {"action": "add", "item": "airbnb", "amount": 500}
"!budget add flight 250 for shrey" -> {"action": "add", "item": "flight", "amount": 250, "notes": "for shrey"}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error parsing budget command: {e}")
        return {"action": "show"}


def find_matching_document(description: str, saved_documents: List) -> Optional[str]:
    """
    Find a document matching the natural language description
    
    Args:
        description: User's description ("the airbnb in hudson yards")
        saved_documents: List of SavedDocument objects
    
    Returns:
        Document ID if found, None otherwise
    """
    if not saved_documents:
        return None
    
    # Format documents for AI
    docs_info = []
    for doc in saved_documents:
        doc_dict = doc.to_dict() if hasattr(doc, 'to_dict') else doc
        docs_info.append({
            "id": doc_dict.get("id"),
            "title": doc_dict.get("title"),
            "type": doc_dict.get("doc_type"),
            "url": doc_dict.get("url"),
            "structured_data": doc_dict.get("structured_data", {})
        })
    
    system_prompt = f"""You are helping find a document that matches the user's description.

Available documents:
{json.dumps(docs_info, indent=2)}

User is looking for: "{description}"

IMPORTANT MATCHING RULES:
- If user says "airbnb" or "vrbo", ONLY match documents with type "airbnb" or "vrbo"
- If user says "google doc", ONLY match documents with type "google_doc"
- Match on title, address, or location mentioned in the description
- Be strict - only return high confidence if it's a clear match

Return JSON with:
- doc_id (string): The ID of the matching document, or null if no good match
- confidence (string): "high", "medium", or "low"
- reason (string): Brief explanation of why this doc matches (or doesn't)"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Find the document matching: {description}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        
        if result.get("confidence") in ["high", "medium"] and result.get("doc_id"):
            return result["doc_id"]
        
        return None
    except Exception as e:
        print(f"Error finding matching document: {e}")
        return None


def suggest_flight_alternatives(flight_criteria: Dict, reason: str = "budget") -> str:
    """
    Generate suggestions for alternative flight options
    
    Args:
        flight_criteria: The original search criteria
        reason: Why alternatives are needed (budget, no_availability, etc.)
    
    Returns:
        Suggestion text
    """
    system_prompt = f"""You are a helpful travel assistant. The user's flight search didn't find good options due to: {reason}.
    
Original search criteria:
{json.dumps(flight_criteria, indent=2)}

Suggest 2-3 smart alternatives like:
- Flying a day earlier/later
- Using nearby airports (e.g., SFO vs OAK vs SJC for SF area)
- Connecting flights if they were searching direct
- Different times of day

Be specific and practical."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "What alternatives would you suggest?"}
            ],
            temperature=0.7
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating suggestions: {e}")
        return "Try searching for flights on different dates or from nearby airports."

