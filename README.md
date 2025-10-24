# 🌍 Travel Planner Bot

An AI-powered travel planning bot for iMessage that helps group chats organize trips by searching for venues, flights, auto-scraping travel documents, and syncing everything to a shared Google Doc.

## ✨ Features

- **🔍 Semantic Search**: Index and search through conversation history to answer questions with AI
- **🏠 Venue Search**: Search Airbnb and Vrbo simultaneously using Stagehand web automation
- **✈️ Flight Search**: Find flights on Google Flights with smart budget-aware suggestions
- **📄 Auto-Scrape Documents**: Paste any Airbnb/Vrbo/Google Doc link and it automatically extracts key info (WiFi, access codes, addresses, check-in times)
- **📝 Google Doc Sync**: Auto-sync all trip details to a shared Google Doc - accommodations, flights, budget, comments, and more
- **💰 Budget Tracking**: Keep track of confirmed expenses with automatic totals and budget alerts
- **💬 Item Management**: Comment on venues/flights, mark items as official, organize everything in one place

## 🚀 Quick Start

### Basic Workflow
1. **Start tracking**: Send `!track` to begin indexing messages
2. **Paste links**: Share Airbnb/Vrbo/Google Doc links - they auto-scrape!
3. **Sync to doc** (optional): Create a Google Doc, share as "edit", run `!sync setup <url>`
4. **Search & ask**: Use `!venue` to search, `!list` to see options, `!ask` to query anything
5. **Mark official**: Use `!official <number>` to finalize choices - auto-syncs to Google Doc

### Prerequisites

- Python 3.9+
- Poetry (for dependency management)
- OpenAI API key
- Browserbase account (API key and Project ID)
- Google Doc (optional, for sync feature)

### Installation

1. **Install Python dependencies**:
   ```bash
   poetry install
   ```

2. **Set up environment variables**:
   Create a `.env` file with the following:
   ```bash
   OPENAI_API_KEY=your-openai-api-key-here
   BROWSERBASE_API_KEY=your-browserbase-api-key
   BROWSERBASE_PROJECT_ID=your-browserbase-project-id
   ```

3. **Run the bot**:
   ```bash
   poetry run python src/main.py
   ```

4. **Set up Google Doc sync** (optional but recommended):
   - Create a new Google Doc
   - Click "Share" → Set to "Anyone with link can **EDIT**"
   - Copy the URL
   - In iMessage, send: `!sync setup <url>`

## 📝 Commands

### Conversation & Search

#### `!track`
Start tracking messages in the current conversation for semantic search.
- `!track` - Start tracking this conversation
- `!track stop` - Stop tracking

Once enabled, all messages are indexed to Chroma for AI-powered `!ask` queries.

#### `!reset`
Clear all indexed messages and reset the message index.
- `!reset` - Delete all indexed messages

#### `!ask [question]`
Ask questions about the trip using natural language. The bot searches through conversation history AND saved documents.
- `!ask what's the airbnb address?`
- `!ask when does Shrey fly in?`
- `!ask what's the wifi password?`
- `!ask how much have we spent so far?`

---

### Venues & Accommodations

#### `!venue [criteria]`
Search for accommodations on Airbnb and Vrbo simultaneously.
- `!venue Lake Tahoe, 4 people, Aug 25-30`
- `!venue cabin in Tahoe, budget $200/night, 6 guests`
- `!venue next` - Show next 3 venues from search results

💡 **Pro tip**: Just paste Airbnb/Vrbo links directly in chat - they're automatically scraped and saved!

---

### Flights

#### `!flight [criteria]`
Search for flights on Google Flights with budget awareness.
- `!flight from SFO to RNO on Aug 25`
- `!flight from SF to Tahoe, budget $300`

---

### Item Management

#### `!list [filter]`
List all saved items (venues, documents, flights).
- `!list` - Show all items
- `!list venues` - Show only venues
- `!list docs` - Show only documents
- `!list flights` - Show only flights
- `!list official` - Show items marked as official

#### `!show <number>`
Show detailed information for a specific item.
- `!show 3` - View details for item #3

#### `!comment <number> <text>`
Add feedback or comments to an item.
- `!comment 3 Love this place!`
- `!comment 5 Too expensive`

#### `!official <number> [number2]...`
Mark item(s) as official for the trip. You can mark multiple items at once.
- `!official 16` - Mark item #16 as official
- `!official 16 23 45` - Mark multiple items

#### `!delete <number>`
Delete an item from the trip.
- `!delete 5` - Delete item #5

---

### Documents

#### `!docs`
List all saved documents (auto-scraped from Airbnb/Vrbo/Google Doc links).
- `!docs` - List all documents
- `!docs delete <number>` - Delete a specific document
- `!docs clear` - Delete all documents

#### `!doc use <number>`
Mark a document as official for the trip.
- `!doc use 1` - Mark document #1 as official
- `!doc remove 1` - Unmark document #1

---

### Google Doc Sync

#### `!sync setup <url>`
Connect to a Google Doc for automatic syncing. The doc will update whenever you add venues, flights, comments, or update the budget.

**Setup Steps**:
1. Create a new Google Doc
2. Share → Set to "Anyone with link can **EDIT**"
3. Copy the URL
4. Run `!sync setup <url>`

#### `!sync now`
Force an immediate sync to the connected Google Doc.

#### `!sync status`
Show sync status and connection details.

#### `!sync enable/disable`
Toggle automatic syncing on or off.

---

### Budget

#### `!budget show`
Display budget summary with all expenses and remaining budget.

#### `!budget set <amount>`
Set the total trip budget.
- `!budget set 5000` - Set budget to $5,000

#### `!budget add [item] [amount]`
Add an expense to the budget ledger.
- `!budget add airbnb 1500`
- `!budget add flight 250`

---

### Trip Status

#### `!trip`
Show all official trip details including accommodations, documents, and key information (WiFi, access codes, etc.).

#### `!status`
Show current trip status including members, venues, flights, budget, and tracking status.

#### `!help`
Display all available commands.

## 🎯 How It Works

### Auto-Scraping Magic
When you paste an Airbnb, Vrbo, or Google Doc link in chat:
1. 🔗 Bot auto-detects the link
2. 🤖 Stagehand scrapes the page in the background (~30 seconds)
3. 📝 Extracts structured data (WiFi passwords, access codes, addresses, check-in times)
4. 💾 Saves to state and indexes text chunks to Chroma for `!ask` queries
5. ✅ Notifies you with a summary

### Google Doc Sync
When you connect a Google Doc with `!sync setup`:
1. 📄 Bot reads the current doc content
2. 🤖 OpenAI generates smart updates (preserves your custom sections)
3. ✏️ Stagehand applies the updates to the doc
4. 🔄 Auto-syncs whenever you: add venues/flights, add comments, mark items official, or update budget
5. 📊 Doc shows: official accommodation, all flights, budget breakdown, recent comments, and all items

### Semantic Search
- All messages (when tracking is enabled) are indexed to Chroma
- Document text chunks from scraped links are also indexed
- `!ask` uses vector search to find relevant context + OpenAI to generate answers

---

## 🏗️ Architecture

### Components

- **main.py**: Bot entry point with all command handlers and message routing
- **models.py**: Data models (Trip, Venue, Flight, Document, etc.) and state management with JSON persistence
- **stagehand_scraper.py**: Stagehand web automation infrastructure for Airbnb/Vrbo/Google Flights
- **google_doc_sync.py**: Orchestrates Google Doc sync process (reading current state, preparing data, triggering sync)
- **stagehand_scripts/sync_google_doc.py**: Stagehand automation for reading and updating Google Docs
- **openai_helpers.py**: OpenAI integration for NLP, Q&A, and intelligent document updates
- **config.py**: Configuration and environment variables

### Data Storage

- **Chroma Vector DB**: Stores and indexes conversation messages + document chunks for semantic search
- **State JSON** (`travel_bot_state.json`): Persists all trip data - members, venues, flights, documents, budget, sync config
- **Browserbase**: Cloud browser automation (no local Chrome needed) - used for web scraping and Google Doc sync
- **Google Docs**: Optional external sync target for sharing trip details with the group

---

**Built with**: iMessage Bot Framework, Stagehand, OpenAI, Chroma
