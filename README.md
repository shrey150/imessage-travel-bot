# 🌍 Travel Planner Bot

An AI-powered travel planning bot for iMessage that helps group chats organize trips by searching for venues, flights, and automatically checking in for flights using Stagehand web automation.

## ✨ Features

- **🔍 Semantic Search**: Index and search through conversation history to answer questions
- **🏠 Venue Search**: Search Airbnb and Vrbo simultaneously using Stagehand
- **✈️ Flight Search**: Find flights on Google Flights with smart budget-aware suggestions
- **💰 Budget Tracking**: Keep track of confirmed expenses and budget
- **🧠 Smart Context**: Learn user preferences and pre-fill search criteria

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- Poetry (for dependency management)
- OpenAI API key
- Browserbase account (API key and Project ID)

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

---

**Built with**: iMessage Bot Framework, Stagehand, OpenAI, Chroma
