import asyncio
import sqlite3
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import time
import re # For extracting ASINs if needed
import random # Added for random delay
import os # For checking file existence
import json # For parsing auth_state.json
import metadata_enrichment

# Constants
TEST_MODE = False  # Set to True to only process the first book, False to process all books
KINDLE_NOTEBOOK_URL = "https://read.amazon.com/notebook"
# Placeholder selectors - REPLACE THESE WITH YOUR FINDINGS from rendered_html.md or manual inspection
BOOK_LIST_SELECTOR = "div.kp-notebook-library-each-book" # Example, adjust
BOOK_TITLE_IN_LIST_SELECTOR = "h2.kp-notebook-searchable" # Example, adjust
BOOK_AUTHOR_IN_LIST_SELECTOR = "p.a-spacing-base.a-spacing-top-mini.a-text-center.a-size-base.a-color-secondary.kp-notebook-searchable" # For author in list view
BOOK_AUTHOR_IN_DETAIL_SELECTOR = "p.a-spacing-none.a-spacing-top-micro.a-size-base.a-color-secondary.kp-notebook-selectable.kp-notebook-metadata" # For author in detail view
BOOK_ASIN_ATTRIBUTE = "id" # If the book div id is the ASIN like B0... # Or 'data-asin'
HIGHLIGHT_SELECTOR = "div[id^='highlight-']" # More robust: "div[id^=highlight-]"
NOTE_SELECTOR = "div[id^='note-']" # More robust: "div[id^=note-]"
HIGHLIGHT_TEXT_SELECTOR = "#highlight" # within highlight div
NOTE_TEXT_SELECTOR = "#note" # within note div
EXPORT_LIMIT_NOTICE_SELECTOR = "div.a-alert-content:has-text('Some highlights have been hidden or truncated due to export limits.')"

DB_NAME = "kindle_highlights.sqlite"
TABLE_NAME = "highlights_notes"

def convert_quotes(text):
    """
    Convert quotes intelligently:
    1. Double curly quotes (""): converted to single straight quotes (')
    2. Single curly quotes:
       - Left single curly quote ('): always converted to double straight quote (")
       - Right single curly quote ('): 
          * If likely an apostrophe: kept as single straight quote (')
          * If likely a quote mark: converted to double straight quote (")
    
    Uses context-based heuristics for differentiating apostrophes from quotation marks.
    """
    # First, handle double curly quotes - using explicit Unicode escape sequences
    # U+201C = left double curly quote, U+201D = right double curly quote
    text = text.replace("\u201c", "'").replace("\u201d", "'")
    
    # Create a function to determine if a character is alphanumeric
    def is_alphanum(char):
        return char.isalnum() if char else False

    # Process single curly quotes with context awareness
    # U+2018 = left single curly quote, U+2019 = right single curly quote
    result = []
    i = 0
    while i < len(text):
        # Check for left single curly quote - always a quotation mark
        if i < len(text) and text[i] == "\u2018":
            result.append('"')  # Convert to double straight quote
        
        # Check for right single curly quote - could be apostrophe or quote
        elif i < len(text) and text[i] == "\u2019":
            # Get context (character before and after)
            prev_char = text[i-1] if i > 0 else ' '
            next_char = text[i+1] if i+1 < len(text) else ' '
            
            # Definite apostrophe cases:
            # 1. Inside a word (like don't, can't) - when both sides are letters
            # 2. After 's' at the end of a word - plural possessive
            if (prev_char.isalpha() and next_char.isalpha()) or \
               (prev_char.lower() == "s" and not is_alphanum(next_char)):
                result.append("'")  # Keep as straight single quote for apostrophes
            # Likely quote mark cases:
            # 1. Quote preceded by a letter and followed by space/punctuation (closing quote)
            # 2. Quote surrounded by spaces/punctuation (isolated quote)
            else:
                result.append('"')  # Convert to double straight quote for quotations
        else:
            result.append(text[i])
        i += 1
    
    return "".join(result)

async def save_auth_state(page, path="auth_state.json"):
    await page.context.storage_state(path=path)
    print(f"Authentication state saved to {path}")

async def initial_login_and_save_state():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False) # Must be headed for login
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(KINDLE_NOTEBOOK_URL, timeout=60000)
        print("Please log in manually in the browser window.")
        print("Once logged in and on the notebook page, press Enter here to save auth state...")
        input() # Wait for user to log in
        await save_auth_state(page)
        await browser.close()

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_title TEXT,
        book_author TEXT,
        book_asin TEXT,
        item_type TEXT, -- 'highlight' or 'note'
        content TEXT,
        original_id TEXT UNIQUE, -- To prevent duplicates
        location TEXT, -- Optional, if you can find it
        date_created TEXT, -- Optional, if you can find it
        book_metadata TEXT, -- New: JSON metadata from enrichment
        retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()
    print(f"Database '{DB_NAME}' and table '{TABLE_NAME}' ensured.")

def is_auth_state_valid(auth_file_path: str) -> bool:
    if not os.path.exists(auth_file_path):
        return False
    try:
        with open(auth_file_path, 'r') as f:
            auth_data = json.load(f)
        
        cookies = auth_data.get('cookies')
        if not cookies or not isinstance(cookies, list):
            print(f"Warning: '{auth_file_path}' has no cookies or cookies format is invalid.")
            return False
        if not cookies: # Empty list of cookies
             print(f"Warning: '{auth_file_path}' contains an empty list of cookies.")
             return False

        current_time = time.time()
        for cookie in cookies:
            if 'expires' in cookie and isinstance(cookie['expires'], (int, float)):
                if cookie['expires'] < current_time:
                    print(f"Authentication state has expired cookie: {cookie.get('name', 'Unnamed cookie')}")
                    return False
        return True # All cookies with 'expires' are valid
    except FileNotFoundError:
        return False # Should be caught by os.path.exists, but as a safeguard
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {auth_file_path}.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while checking auth state {auth_file_path}: {e}")
        return False

async def scrape_kindle_highlights():
    setup_database()
    limited_export_books = []
    all_collected_data = [] # To store data before batch writing to DB
    processed_note_ids = set() # Track which notes have been processed with highlights

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) # Can be headless now
        try:
            context = await browser.new_context(storage_state="auth_state.json")
        except FileNotFoundError:
            print("Error: auth_state.json not found. Run initial_login_and_save_state() first.")
            return

        page = await context.new_page()
        await page.goto(KINDLE_NOTEBOOK_URL, timeout=90000, wait_until="networkidle")
        print("Navigated to Kindle Notebook.")
        await page.wait_for_timeout(5000) # Give it a moment to settle

        # --- Get List of Books ---
        try:
            await page.wait_for_selector(BOOK_LIST_SELECTOR, timeout=30000)
        except PlaywrightTimeoutError:
            print(f"Timeout waiting for book list with selector: {BOOK_LIST_SELECTOR}")
            print("Page content:", await page.content()) # For debugging
            await browser.close()
            return

        book_elements = await page.locator(BOOK_LIST_SELECTOR).all()
        print(f"Found {len(book_elements)} potential book entries.")
        if not book_elements:
            print("No books found. Check BOOK_LIST_SELECTOR or rendered_html.md")
            await browser.close()
            return

        # Iterate through each book
        for i in range(len(book_elements)):
            current_book_elements = await page.locator(BOOK_LIST_SELECTOR).all()
            if i >= len(current_book_elements):
                print(f"Index {i} out of bounds for current book elements. Stopping.")
                break
            
            book_element = current_book_elements[i]
            
            book_title = "Unknown Title"
            book_author = "Unknown Author"
            book_asin = "UnknownASIN"

            try:
                title_locator = book_element.locator(BOOK_TITLE_IN_LIST_SELECTOR)
                if await title_locator.count() > 0:
                    book_title = (await title_locator.first.text_content() or "").strip()
                else:
                    book_title = "Unknown Title" # Default if not found
                
                author_locator = book_element.locator(BOOK_AUTHOR_IN_LIST_SELECTOR)
                if await author_locator.count() > 0:
                    author_text = (await author_locator.first.text_content() or "").strip()
                    # Clean up the author text by removing "By: " prefix if present
                    book_author = author_text.replace("By:", "").strip() if "By:" in author_text else author_text
                else:
                    book_author = "Unknown Author" # Default if not found
                
                raw_book_id = await book_element.get_attribute(BOOK_ASIN_ATTRIBUTE)
                # Try to extract ASIN from common patterns in id or data-asin
                if raw_book_id:
                    match = re.search(r"([A-Z0-9]{10})", raw_book_id) # Look for 10-char alphanumeric string
                    if match:
                        book_asin = match.group(1)
                    else:
                        book_asin = f"custom_id_{raw_book_id}" # Fallback
                
                print(f"\nProcessing book ({i+1}/{len(book_elements)}): {book_title} (Author: {book_author}) (ASIN/ID: {book_asin})")

                # Enrich metadata using ASIN -> ISBN -> Google Books
                book_metadata = metadata_enrichment.enrich_book_metadata(book_title, book_author, book_asin)
                
                await book_element.click()
                
                try:
                    # Wait for highlights/notes to load. This selector might need adjustment.
                    # The plan suggests: await page.wait_for_selector(f"{HIGHLIGHT_SELECTOR}, {NOTE_SELECTOR}", timeout=20000)
                    # Let's use a more general approach: wait for any highlight or note to appear.
                    await page.wait_for_selector(f'{HIGHLIGHT_SELECTOR}, {NOTE_SELECTOR}', timeout=20000)
                    print("Highlights/notes section loaded.")
                    
                    # Try to get author from detail view if we don't have good author info yet
                    if book_author == "Unknown Author" or not book_author:
                        # Wait a bit for the detail view to fully load
                        await page.wait_for_timeout(1000)
                        # Try to find author in the detail view
                        detail_author_locator = page.locator(BOOK_AUTHOR_IN_DETAIL_SELECTOR)
                        if await detail_author_locator.count() > 0:
                            book_author = (await detail_author_locator.first.text_content() or "").strip()
                            print(f"Updated author from detail view: {book_author}")
                except PlaywrightTimeoutError:
                    print(f"Timeout waiting for highlights/notes to load for {book_title}. Skipping this book's highlights.")
                    # If book list isn't stable, might need to page.go_back() and re-wait for BOOK_LIST_SELECTOR
                    continue
                
                await page.wait_for_timeout(2000) # Extra buffer

                if await page.is_visible(EXPORT_LIMIT_NOTICE_SELECTOR):
                    print(f"WARNING: Export limit notice found for '{book_title}'.")
                    if book_title not in limited_export_books:
                        limited_export_books.append(book_title)
                
                # Process highlights first, checking for associated notes
                highlight_divs = await page.locator(HIGHLIGHT_SELECTOR).all()
                highlight_count = 0
                highlight_with_note_count = 0
                
                for hl_div in highlight_divs:
                    original_id = await hl_div.get_attribute("id")
                    text_locator = hl_div.locator(HIGHLIGHT_TEXT_SELECTOR)
                    text_content = ""
                    if await text_locator.count() > 0:
                        text_content = (await text_locator.first.text_content() or "").strip()
                    
                    if text_content and original_id:
                        # Convert curly quotes and then quote the highlight
                        text_content = convert_quotes(text_content)
                        quoted_highlight = f'"{text_content}"'
                        final_content = quoted_highlight
                        
                        # Check for associated note that appears near this highlight
                        associated_note_locator = page.locator(f'{NOTE_SELECTOR}:near(#{original_id})')
                        has_associated_note = await associated_note_locator.count() > 0
                        
                        if has_associated_note:
                            associated_note = associated_note_locator.first
                            note_id = await associated_note.get_attribute("id")
                            note_text_locator = associated_note.locator(NOTE_TEXT_SELECTOR)
                            
                            if await note_text_locator.count() > 0:
                                note_text = (await note_text_locator.first.text_content() or "").strip()
                                if note_text:
                                    # Also convert curly quotes in the note text
                                    note_text = convert_quotes(note_text)
                                    # Append note to the quoted highlight with a space
                                    final_content = f"{quoted_highlight} {note_text}"
                                    processed_note_ids.add(note_id)
                                    highlight_with_note_count += 1
                        
                        all_collected_data.append({
                            "book_title": book_title,
                            "book_author": book_author,
                            "book_asin": book_asin,
                            "item_type": "highlight",
                            "content": final_content,
                            "original_id": original_id,
                            "book_metadata": json.dumps(book_metadata) if book_metadata else None
                        })
                        highlight_count += 1
                
                print(f"Found {highlight_count} highlights for {book_title}, of which {highlight_with_note_count} have associated notes.")

                # Process orphaned notes (notes without highlights)
                note_divs = await page.locator(NOTE_SELECTOR).all()
                orphan_note_count = 0
                
                for nt_div in note_divs:
                    original_id = await nt_div.get_attribute("id")
                    
                    # Skip notes that were already processed with highlights
                    if original_id in processed_note_ids:
                        continue
                    
                    text_locator = nt_div.locator(NOTE_TEXT_SELECTOR)
                    text_content = ""
                    if await text_locator.count() > 0:
                        text_content = (await text_locator.first.text_content() or "").strip()
                    
                    if text_content and original_id:
                        # Convert curly quotes in orphaned notes
                        text_content = convert_quotes(text_content)
                        all_collected_data.append({
                            "book_title": book_title,
                            "book_author": book_author,
                            "book_asin": book_asin,
                            "item_type": "note",
                            "content": text_content,
                            "original_id": original_id,
                            "book_metadata": json.dumps(book_metadata) if book_metadata else None
                        })
                        orphan_note_count += 1
                
                print(f"Found {orphan_note_count} orphaned notes for {book_title}.")

            except PlaywrightTimeoutError as e:
                print(f"Timeout error processing book {book_title}: {e}")
            except Exception as e:
                print(f"An error occurred processing book {book_title}: {e}")
            
            await page.wait_for_timeout(1000 + random.randint(0,1000)) # Random delay
            
            # If in test mode, break after processing the first book
            if TEST_MODE and i == 0:
                print("TEST MODE: Only processing the first book. Set TEST_MODE = False to process all books.")
                break

    if all_collected_data:
        conn = sqlite3.connect(DB_NAME)
        try:
            # Using INSERT OR IGNORE for robustness with UNIQUE constraint
            cursor = conn.cursor()
            for row in all_collected_data:
                cols = ', '.join([f'"{col}"' for col in row.keys()]) # Quote column names
                placeholders = ', '.join('?' * len(row))
                sql = f"INSERT OR IGNORE INTO \"{TABLE_NAME}\" ({cols}) VALUES ({placeholders})"
                try:
                    cursor.execute(sql, list(row.values()))
                except sqlite3.InterfaceError as ie:
                    print(f"SQLite InterfaceError for row {row}: {ie}. SQL: {sql}") # Debug specific row error
            conn.commit()
            print(f"\nSuccessfully saved/updated {len(all_collected_data)} items to SQLite database: {DB_NAME}")
        except sqlite3.IntegrityError as e:
             print(f"SQLite Integrity Error (likely duplicate original_id): {e}. Some rows might not have been inserted.")
        except Exception as e:
            print(f"Error saving to SQLite: {e}")
        finally:
            conn.close()

    print("\n--- Summary ---")
    print(f"Total items collected: {len(all_collected_data)}")
    if limited_export_books:
        print("Books with export limit notices:")
        for book in limited_export_books:
            print(f" - {book}")
    else:
        print("No export limit notices encountered.")

    await browser.close()

if __name__ == "__main__":
    auth_file = "auth_state.json"
    
    if is_auth_state_valid(auth_file):
        print(f"Found valid {auth_file}. Attempting to scrape highlights.")
        asyncio.run(scrape_kindle_highlights())
    else:
        if os.path.exists(auth_file):
            print(f"{auth_file} found but is invalid or expired. Attempting to re-authenticate.")
            try:
                os.remove(auth_file)
                print(f"Removed old/invalid {auth_file}.")
            except OSError as e:
                print(f"Error removing old {auth_file}: {e}. Please remove it manually if issues persist.")
        else:
            print(f"{auth_file} not found. Starting initial login process.")
        
        asyncio.run(initial_login_and_save_state())
        print(f"Login state presumably saved to {auth_file}. Please re-run the script to start scraping.")