# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Trip.com flight scraper built with Python and Playwright. The scraper automates clicking through flight cards, opens modal dialogs to extract detailed fare information, and saves structured flight data to JSON files.

## Development Setup

This project uses `uv` for dependency management. To set up:

```bash
# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium

# Run the scraper
uv run python main.py
```

## Architecture

The scraper is implemented as a single `TripFlightScraper` class in `main.py` with these key components:

### Core Scraping Flow
1. **Navigation**: Load Trip.com search results page with anti-detection measures
2. **Card Discovery**: Find flight cards using fallback selectors (`.result-item.J_FlightItem` or `[data-testid^="u-flight-card-"]`)
3. **Modal Interaction**: Click select buttons to open fare modals, extract detailed pricing, then close modals
4. **Data Extraction**: Extract both basic flight info and detailed fare options from modals
5. **JSON Export**: Save structured data with timestamp

### Key Methods
- `scrape_flights()`: Main orchestration method
- `extract_flight_basic_info()`: Extract basic flight data from cards
- `extract_modal_fare_options()`: Extract detailed fare data from modals
- `extract_baggage_info()` & `extract_flexibility_info()`: Extract specific fare details

### Data Structure
The scraper produces JSON with:
- `search_info`: Route, date, search time metadata
- `flights[]`: Array of flight objects with basic info + `fare_options[]` array from modals

## Common Issues

### Modal Closing Problems
The scraper frequently encounters modal overlay issues where subsequent flight cards can't be clicked due to lingering modal overlays. The current implementation tries multiple closing strategies but may need more robust handling.

### Element Staleness
The scraper re-queries elements in each loop iteration to avoid stale DOM references, which is critical for the dynamic Trip.com page.

### Rate Limiting
Uses 2-second delays between flight card interactions and various anti-detection measures (custom user agent, viewport, headers).

## Testing

Run the scraper with visible browser for debugging:
```bash
# Edit main.py to set headless=False
uv run python main.py
```

Output files are timestamped JSON files like `trip_flights_YYYYMMDD_HHMMSS.json`.