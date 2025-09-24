import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TripFlightScraper:
    def __init__(self, headless=True, timeout=30000):
        self.headless = headless
        self.timeout = timeout
        self.flights_data = {
            "search_info": {
                "route": "KUL → DAC",
                "date": "2025-10-01",
                "search_time": datetime.now().isoformat(),
                "currency": "MYR"
            },
            "flights": []
        }

    async def scrape_flights(self, url):
        """Main scraping function"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
                }
            )
            page = await context.new_page()

            try:
                logger.info(f"Navigating to: {url}")

                # Try different wait strategies
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    logger.info("Page loaded with domcontentloaded")
                except Exception as e:
                    logger.warning(f"domcontentloaded failed: {e}")
                    await page.goto(url, wait_until="load", timeout=30000)
                    logger.info("Page loaded with load event")

                # Wait a bit for dynamic content
                await asyncio.sleep(3)

                # Try to wait for flight results
                try:
                    await page.wait_for_selector('.result-item.J_FlightItem', timeout=20000)
                    logger.info("Flight results found")
                except Exception as e:
                    logger.warning(f"Flight results not found: {e}")
                    # Try alternative selectors
                    try:
                        await page.wait_for_selector('[data-testid="u-flight-card-1"]', timeout=10000)
                        logger.info("Alternative flight selector found")
                    except Exception as e2:
                        logger.error(f"No flight results found with any selector: {e2}")
                        # Take screenshot for debugging
                        await page.screenshot(path="debug_screenshot.png")
                        logger.info("Debug screenshot saved as debug_screenshot.png")
                        return self.flights_data

                # Get all flight cards with fallback selectors
                flight_cards = await page.query_selector_all('.result-item.J_FlightItem')
                if not flight_cards:
                    flight_cards = await page.query_selector_all('[data-testid^="u-flight-card-"]')

                if not flight_cards:
                    logger.error("No flight cards found with any selector")
                    return self.flights_data

                logger.info(f"Found {len(flight_cards)} flight cards")

                for i in range(len(flight_cards)):
                    try:
                        logger.info(f"Processing flight {i+1}/{len(flight_cards)}")

                        # Re-query flight cards to avoid stale references
                        current_flight_cards = await page.query_selector_all('.result-item.J_FlightItem')
                        if not current_flight_cards:
                            current_flight_cards = await page.query_selector_all('[data-testid^="u-flight-card-"]')

                        if i >= len(current_flight_cards):
                            logger.warning(f"Flight card {i+1} no longer exists")
                            continue

                        card = current_flight_cards[i]
                        flight_data = await self.extract_flight_basic_info(card)

                        # Find and click select button using page-level selector with index
                        select_buttons = await page.query_selector_all('button[data-testid="u_select_btn"]')
                        if i < len(select_buttons):
                            try:
                                # Scroll to button first
                                await select_buttons[i].scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)

                                await select_buttons[i].click()
                                logger.info(f"Clicked select button for flight {i+1}")

                                # Wait for modal to appear
                                await page.wait_for_selector('.flt-page-v2-modal', timeout=15000)

                                # Extract detailed fare information from modal
                                fare_options = await self.extract_modal_fare_options(page)
                                flight_data['fare_options'] = fare_options

                                # Close modal with multiple attempts
                                for attempt in range(3):
                                    try:
                                        close_btn = await page.query_selector('.flt-page-v2-modal-head [data-testid="page_modal_close_btn"]')
                                        if close_btn:
                                            await close_btn.click()
                                            await page.wait_for_selector('.flt-page-v2-modal', state='hidden', timeout=5000)
                                            break
                                    except Exception as close_e:
                                        logger.warning(f"Close attempt {attempt+1} failed: {close_e}")
                                        if attempt == 2:
                                            # Force close with Escape key
                                            await page.keyboard.press('Escape')
                                            await asyncio.sleep(1)

                            except Exception as click_e:
                                logger.error(f"Error clicking select button for flight {i+1}: {click_e}")

                        self.flights_data['flights'].append(flight_data)

                        # Longer delay between flights to avoid rate limiting
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error(f"Error processing flight {i+1}: {str(e)}")
                        continue

            except Exception as e:
                logger.error(f"Error during scraping: {str(e)}")
            finally:
                await browser.close()

        return self.flights_data

    async def extract_flight_basic_info(self, card):
        """Extract basic flight info from flight card"""
        flight_data = {
            "flight_id": None,
            "airline": None,
            "flight_number": None,
            "aircraft": None,
            "route": {
                "departure": {
                    "airport": None,
                    "terminal": None,
                    "city": None,
                    "time": None,
                    "date": None
                },
                "arrival": {
                    "airport": None,
                    "terminal": None,
                    "city": None,
                    "time": None,
                    "date": None
                }
            },
            "duration": None,
            "amenities": [],
            "co2_reduction": None,
            "availability_warning": None,
            "base_price": None
        }

        try:
            # Get flight ID
            flight_id = await card.get_attribute('data-flight-id')
            flight_data['flight_id'] = flight_id

            # Airline name
            airline_elem = await card.query_selector('.flights-name')
            if airline_elem:
                flight_data['airline'] = await airline_elem.get_attribute('title')

            # Departure and arrival times
            time_elements = await card.query_selector_all('.time_cbcc span')
            if len(time_elements) >= 2:
                flight_data['route']['departure']['time'] = await time_elements[0].inner_text()
                flight_data['route']['arrival']['time'] = await time_elements[1].inner_text()

            # Airport codes
            airport_codes = await card.query_selector_all('.flight-info-stop__code_e162')
            if len(airport_codes) >= 2:
                dep_airport = await airport_codes[0].inner_text()
                arr_airport = await airport_codes[1].inner_text()

                # Parse airport and terminal (e.g., "KUL T1" -> airport="KUL", terminal="T1")
                dep_parts = dep_airport.strip().split()
                arr_parts = arr_airport.strip().split()

                flight_data['route']['departure']['airport'] = dep_parts[0] if dep_parts else None
                flight_data['route']['departure']['terminal'] = dep_parts[1] if len(dep_parts) > 1 else None
                flight_data['route']['arrival']['airport'] = arr_parts[0] if arr_parts else None
                flight_data['route']['arrival']['terminal'] = arr_parts[1] if len(arr_parts) > 1 else None

            # Duration
            duration_elem = await card.query_selector('.flight-info-duration_576d span')
            if duration_elem:
                flight_data['duration'] = await duration_elem.inner_text()

            # Base price
            price_elem = await card.query_selector('[data-price]')
            if price_elem:
                price_value = await price_elem.get_attribute('data-price')
                flight_data['base_price'] = int(price_value) if price_value else None

            # Amenities
            amenity_icons = await card.query_selector_all('.comfort-icon-item')
            amenities = []
            for icon in amenity_icons:
                class_list = await icon.get_attribute('class')
                if 'fi-icon_charging' in class_list:
                    amenities.append('charging')
                elif 'fi-icon_dinner_new' in class_list:
                    amenities.append('meal')
                elif 'fi-icon_wifi_new' in class_list:
                    amenities.append('wifi')
                elif 'fi-icon_show' in class_list:
                    amenities.append('entertainment')
            flight_data['amenities'] = amenities

            # Check for CO2 reduction
            co2_elem = await card.query_selector('[data-testid="list_label_co2"]')
            if co2_elem:
                co2_text = await co2_elem.inner_text()
                flight_data['co2_reduction'] = co2_text.strip()

            # Check availability warning
            availability_elem = await card.query_selector('.book-btn-left')
            if availability_elem:
                availability_text = await availability_elem.inner_text()
                if '<5 left' in availability_text:
                    flight_data['availability_warning'] = availability_text.strip()

        except Exception as e:
            logger.error(f"Error extracting basic flight info: {str(e)}")

        return flight_data

    async def extract_modal_fare_options(self, page):
        """Extract fare options from the modal"""
        fare_options = []

        try:
            # Wait for modal content to load
            await page.wait_for_selector('.result-item-flex__wrapper', timeout=10000)

            # Get flight details from modal header
            flight_details = await self.extract_modal_flight_details(page)

            # Get all fare option cards
            fare_cards = await page.query_selector_all('.result-item-flex__wrapper')

            for card in fare_cards:
                try:
                    fare_option = {
                        "fare_type": None,
                        "price": None,
                        "original_price": None,
                        "selected": False,
                        "baggage": {
                            "carry_on": None,
                            "checked": None
                        },
                        "flexibility": {
                            "cancellation_fee": None,
                            "change_fee": None
                        }
                    }

                    # Check if this option is selected
                    radio_selected = await card.query_selector('[aria-checked="true"]')
                    fare_option['selected'] = radio_selected is not None

                    # Get cabin class/fare type
                    cabin_elem = await card.query_selector('.result-item-flex-class__cabin')
                    if cabin_elem:
                        fare_type = await cabin_elem.inner_text()
                        fare_option['fare_type'] = fare_type.strip()

                    # Check for recommended tag
                    recommended_elem = await card.query_selector('.result-item-flex__title-recommend')
                    if recommended_elem:
                        fare_option['fare_type'] = f"{fare_option['fare_type']} Recommended"

                    # Get price
                    price_elem = await card.query_selector('[data-price]')
                    if price_elem:
                        price_value = await price_elem.get_attribute('data-price')
                        fare_option['price'] = int(price_value) if price_value else None

                    # Get original price (crossed out price)
                    original_price_elem = await card.query_selector('.item-con-price__del')
                    if original_price_elem:
                        original_text = await original_price_elem.inner_text()
                        # Extract number from "MYR 1,447"
                        original_match = re.search(r'MYR\s*([\d,]+)', original_text)
                        if original_match:
                            fare_option['original_price'] = int(original_match.group(1).replace(',', ''))

                    # Extract baggage information
                    baggage_info = await self.extract_baggage_info(card)
                    fare_option['baggage'] = baggage_info

                    # Extract flexibility information
                    flexibility_info = await self.extract_flexibility_info(card)
                    fare_option['flexibility'] = flexibility_info

                    fare_options.append(fare_option)

                except Exception as e:
                    logger.error(f"Error extracting fare option: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting modal fare options: {str(e)}")

        return fare_options

    async def extract_modal_flight_details(self, page):
        """Extract detailed flight info from modal header"""
        details = {
            "airline": None,
            "flight_number": None,
            "aircraft": None
        }

        try:
            # Airline name
            airline_elem = await page.query_selector('.flight-info-airline-name')
            if airline_elem:
                details['airline'] = await airline_elem.inner_text()

            # Flight number
            flight_no_elem = await page.query_selector('.flight-info-flightNo')
            if flight_no_elem:
                details['flight_number'] = await flight_no_elem.inner_text()

            # Aircraft
            aircraft_elem = await page.query_selector('.flight-info-craft')
            if aircraft_elem:
                details['aircraft'] = await aircraft_elem.inner_text()

        except Exception as e:
            logger.error(f"Error extracting modal flight details: {str(e)}")

        return details

    async def extract_baggage_info(self, card):
        """Extract baggage information from fare card"""
        baggage = {
            "carry_on": None,
            "checked": None
        }

        try:
            # Find baggage hover area
            baggage_hover = await card.query_selector('[data-testid="label_Baggage_hover"]')
            if baggage_hover:
                # Get carry-on info
                carryon_elems = await baggage_hover.query_selector_all('.carryon .title-content')
                for elem in carryon_elems:
                    text = await elem.inner_text()
                    if 'Carry-on baggage:' in text:
                        baggage['carry_on'] = text.replace('Carry-on baggage:', '').strip()
                    elif 'Checked baggage:' in text:
                        baggage['checked'] = text.replace('Checked baggage:', '').strip()

        except Exception as e:
            logger.error(f"Error extracting baggage info: {str(e)}")

        return baggage

    async def extract_flexibility_info(self, card):
        """Extract cancellation and change fee information"""
        flexibility = {
            "cancellation_fee": None,
            "change_fee": None
        }

        try:
            # Find refund fee
            refund_elem = await card.query_selector('[data-testid="label_REFUND_FEE"] .refund-fee')
            if refund_elem:
                flexibility['cancellation_fee'] = await refund_elem.inner_text()

            # Find change fee
            change_elem = await card.query_selector('[data-testid="label_CHANGE_FEE"] .special-text span')
            if change_elem:
                flexibility['change_fee'] = await change_elem.inner_text()

        except Exception as e:
            logger.error(f"Error extracting flexibility info: {str(e)}")

        return flexibility

    def save_to_json(self, filename=None):
        """Save scraped data to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"trip_flights_{timestamp}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.flights_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Data saved to {filename}")
        return filename

async def main():
    """Main function to run the scraper"""
    url = "https://www.trip.com/flights/showfarefirst?dcity=kul&acity=dac&ddate=2025-10-01&rdate=2025-10-04&triptype=ow&class=y&lowpricesource=searchform&quantity=1&searchboxarg=t&nonstoponly=off&locale=en-XX&curr=MYR"

    scraper = TripFlightScraper(headless=False, timeout=60000)  # Set to False to see browser

    logger.info("Starting flight scraping...")
    data = await scraper.scrape_flights(url)

    # Save to JSON
    filename = scraper.save_to_json()

    logger.info(f"Scraping completed! Found {len(data['flights'])} flights")
    logger.info(f"Data saved to {filename}")

if __name__ == "__main__":
    asyncio.run(main())
