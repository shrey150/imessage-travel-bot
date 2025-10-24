# 🌍 Travel Planner Bot

An AI-powered travel planning bot for iMessage that helps group chats organize trips by searching for venues, flights, and automatically checking in for flights using Stagehand web automation.

## ✨ Features

- **🔍 Semantic Search**: Index and search through conversation history to answer questions
- **🏠 Venue Search**: Search Airbnb and Vrbo simultaneously using Stagehand
- **✈️ Flight Search**: Find flights on Google Flights with smart budget-aware suggestions
- **🎫 Auto Check-In**: Automatically check in for flights 24 hours before departure (V1)
- **💰 Budget Tracking**: Keep track of confirmed expenses and budget
- **🧠 Smart Context**: Learn user preferences and pre-fill search criteria

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- Poetry (for dependency management)
- OpenAI API key
- Browserbase account (API key and Project ID)

### Installation

1. **Navigate to the bot directory**:
   ```bash
   cd examples/travel-bot
   ```

2. **Install Python dependencies**:
   ```bash
   poetry install
   ```

3. **Set up environment variables**:
   Create a `.env` file with the following:
   ```bash
   OPENAI_API_KEY=your-openai-api-key-here
   BROWSERBASE_API_KEY=your-browserbase-api-key
   BROWSERBASE_PROJECT_ID=your-browserbase-project-id
   DEBUG=true
   ```

4. **Run the bot**:
   ```bash
   poetry run python main.py
   ```

## 📝 Commands

### `!track`
Start tracking messages in the current conversation for semantic search.

**Usage**:
- `!track` - Start tracking this conversation
- `!track stop` - Stop tracking

Once tracking is enabled, all messages in the conversation will be indexed to Chroma for the `!ask` command.

### `!reset`
Clear all indexed messages and reset the message index.

**Usage**:
- `!reset` - Delete all indexed messages

Useful for testing or starting fresh.

### `!ask [question]`
Ask questions about the trip using natural language.

**Examples**:
- `!ask what's the airbnb address?`
- `!ask when does Shrey fly in?`
- `!ask how much have we spent so far?`

### `!venue [criteria]`
Search for accommodations on Airbnb and Vrbo.

**Examples**:
- `!venue Lake Tahoe, 4 people, Aug 25-30`
- `!venue cabin in Tahoe, budget $200/night, 6 guests`

### `!flight [member] [criteria]`
Search for flights on Google Flights.

**Examples**:
- `!flight Shrey from SFO to RNO on Aug 25`
- `!flight from SF to Tahoe, budget $300`

### `!checkin [member]`
Automatically check in for a flight (requires confirmation code and last name).

**Examples**:
- `!checkin` (checks in the sender)
- `!checkin Shrey`

### `!budget show`
Display budget summary and all expenses.

### `!budget add [item] [amount]`
Add an expense to the budget ledger.

**Examples**:
- `!budget add airbnb 500`
- `!budget add flight 250 for shrey`

### `!status`
Show current trip status including members, venues, flights, and budget.

### `!help`
Display all available commands.

## 🏗️ Architecture

### Components

- **main.py**: Bot entry point with command handlers
- **models.py**: Data models and state management
- **stagehand_scraper.py**: Stagehand web automation infrastructure
- **openai_helpers.py**: OpenAI integration for NLP and Q&A
- **config.py**: Configuration and environment variables

### Data Storage

- **Chroma Vector DB**: Stores and indexes conversation messages for semantic search
- **State JSON**: Persists trip data, member info, venues, flights, and budget
- **Browserbase**: Uses Browserbase cloud for remote browser automation (no local browser needed)

## 🎯 Showcase Features

### Stagehand/BrowserBase Automation

This bot demonstrates the power of Stagehand for real-world web automation:

1. **Hybrid Scraping**: Constructs URLs programmatically (resilient) but uses Stagehand's AI extraction (resilient to UI changes)
2. **Parallel Execution**: Searches Airbnb and Vrbo simultaneously for faster results
3. **Complex Workflows**: Navigates multi-step airline check-in processes
4. **Natural Language**: Uses Stagehand's `act()` and `extract()` for human-like interactions

## 🛠️ Development

### V0 Simplifications

- Single global trip (no multi-tenancy)
- Hardcoded conversation ID
- No message classification (indexes everything)
- Local Stagehand mode only

### Future Enhancements (V1+)

- [ ] Multi-tenant support with SQLite
- [ ] Message classification for better indexing
- [ ] Google Sheets sync for budget
- [ ] Scheduled automatic check-ins
- [ ] More airlines (JetBlue, Alaska, etc.)
- [ ] More venue sources (hotels, resorts)
- [ ] Flight booking integration
- [ ] Calendar integration

## 📊 Data Model

### Trip
- name, destination, dates, tracking status

### Member
- name, location, budget, flight_criteria, notes

### Venue
- Airbnb/Vrbo listing details with prices, ratings, amenities

### Flight
- Flight options with airline, times, price, route

### Budget Entry
- Expense tracking with item, amount, date, paid_by

## 🐛 Troubleshooting

### Stagehand Issues

If Stagehand fails to install or run:

1. Ensure Node.js is installed: `node --version`
2. Check OpenAI API key is set in `.env`
3. For local mode, ensure Chrome/Chromium is installed
4. Check timeout settings in `config.py`

### Chroma Issues

If message indexing fails:

1. Ensure `chroma_db/` directory exists and is writable
2. Try deleting `chroma_db/` and restarting the bot
3. Check for conflicting Chroma versions

### Message Not Indexing

Verify `TARGET_CONVERSATION_ID` matches your actual group chat ID in BlueBubbles.

## 📄 License

MIT License - See main project LICENSE file

## 🤝 Contributing

Contributions welcome! This is an example bot showcasing Stagehand capabilities.

---

**Built with**: iMessage Bot Framework, Stagehand, OpenAI, Chroma

