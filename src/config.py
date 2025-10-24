"""
Configuration for Travel Planner Bot
"""

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

BOT_NAME = "Travel Planner Bot"
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

CHROMA_PERSIST_DIRECTORY = "./chroma_db"
CHROMA_COLLECTION_NAME = "trip_messages"

STATE_FILE_PATH = "travel_bot_state.json"

STAGEHAND_TIMEOUT = 120
STAGEHAND_ENV = "BROWSERBASE"
BROWSERBASE_PROJECT_ID = os.getenv("BROWSERBASE_PROJECT_ID")
BROWSERBASE_API_KEY = os.getenv("BROWSERBASE_API_KEY")

MAX_VENUES_TO_STORE = 10
MAX_FLIGHTS_TO_STORE = 5
VENUE_SEARCH_TIMEOUT = 90
FLIGHT_SEARCH_TIMEOUT = 90

CHECKIN_WINDOW_HOURS = 24
SUPPORTED_AIRLINES = ["United", "Southwest", "Delta", "American"]

