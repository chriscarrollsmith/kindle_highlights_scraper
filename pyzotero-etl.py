import os
import sqlite3
from dotenv import load_dotenv
from pyzotero import zotero

# --- Configuration ---
DB_NAME = "kindle_highlights.sqlite"
HIGHLIGHTS_TABLE_NAME = "highlights_notes"
ZOTERO_COLLECTION_NAME = "Kindle Highlights"

def main():
    # Load environment variables from .env file
    load_dotenv()
    zotero_api_key = os.getenv("ZOTERO_API_KEY")
    zotero_library_id = os.getenv("ZOTERO_LIBRARY_ID")
    zotero_library_type = os.getenv("ZOTERO_LIBRARY_TYPE")

    if not all([zotero_api_key, zotero_library_id, zotero_library_type]):
        print("Error: ZOTERO_API_KEY, ZOTERO_LIBRARY_ID, and ZOTERO_LIBRARY_TYPE must be set in .env file.")
        return

    print(f"Connecting to Zotero library ID: {zotero_library_id}, type: {zotero_library_type}")
    zot = zotero.Zotero(zotero_library_id, zotero_library_type, zotero_api_key)

    # 1. Ensure "Kindle Highlights" collection exists
    collection_id = get_or_create_collection(zot, ZOTERO_COLLECTION_NAME)
    if not collection_id:
        print(f"Could not find or create collection '{ZOTERO_COLLECTION_NAME}'. Exiting.")
        return
    print(f"Using Zotero collection: '{ZOTERO_COLLECTION_NAME}' (ID: {collection_id})")

    # 2. Connect to SQLite and fetch data
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Get unique books first
    cursor.execute(f"SELECT DISTINCT book_title, book_author, book_asin FROM {HIGHLIGHTS_TABLE_NAME}")
    unique_books = cursor.fetchall()
    print(f"Found {len(unique_books)} unique books in the database.")

    processed_books = 0
    processed_notes = 0

    for book_title, book_author, book_asin in unique_books:
        if not book_title or book_title == "Unknown Title":
            print(f"Skipping book with missing or unknown title (ASIN: {book_asin}).")
            continue
            
        print(f"\nProcessing book: {book_title} by {book_author if book_author else 'Unknown Author'}")

        # 2a. Create a Zotero item for the book if one doesn't already exist
        zotero_book_item = get_or_create_book_item(zot, collection_id, book_title, book_author, book_asin)
        if not zotero_book_item:
            print(f"  Could not create or find Zotero item for book: {book_title}. Skipping its highlights.")
            continue
        
        book_item_key = zotero_book_item['key']
        print(f"  Using Zotero book item: {book_title} (Key: {book_item_key})")
        processed_books +=1

        # 2b. Fetch and create Zotero notes for highlights/notes of this book
        cursor.execute(f"""
            SELECT content, item_type, original_id 
            FROM {HIGHLIGHTS_TABLE_NAME} 
            WHERE book_title = ? AND (book_author = ? OR (? IS NULL AND book_author IS NULL)) AND book_asin = ?
        """, (book_title, book_author, book_author, book_asin))
        
        items_for_book = cursor.fetchall()
        print(f"  Found {len(items_for_book)} highlights/notes for this book in the database.")

        for content, item_type, original_id in items_for_book:
            # Removed duplicate checking logic based on original_id as per user request
            # All notes/highlights from the DB will be added.
            
            success = add_note_to_item(zot, book_item_key, content, item_type, original_id)
            if success:
                print(f"    Successfully added {item_type} (ID: {original_id}) to Zotero for '{book_title}'.")
                processed_notes += 1

    conn.close()
    print(f"\n--- Import Summary ---")
    print(f"Processed {processed_books} unique books.")
    print(f"Added {processed_notes} new notes/highlights to Zotero.")
    print("Process complete.")

def get_or_create_collection(zot_client, collection_name):
    """Gets the ID of a collection by name, or creates it if it doesn't exist."""
    collections = zot_client.collections()
    for coll in collections:
        if coll['data']['name'] == collection_name:
            return coll['key']
    
    # If not found, create it
    print(f"Collection '{collection_name}' not found. Creating it...")
    try:
        resp = zot_client.create_collections([{'name': collection_name}])
        if resp['success']:
            # The response gives an index '0' for the first (and in this case, only) created collection
            new_collection_key = resp['success']['0']
            print(f"Collection '{collection_name}' created successfully with key: {new_collection_key}")
            return new_collection_key
        else:
            print(f"Failed to create collection '{collection_name}'. Response: {resp}")
            return None
    except Exception as e:
        print(f"Error creating collection '{collection_name}': {e}")
        return None

def get_or_create_book_item(zot_client, collection_id, title, author, asin):
    """
    Gets a Zotero book item by title within a specific collection, 
    or creates it if it doesn't exist. Adds ASIN to the 'extra' field for better identification.
    """
    # Search for the book by title. Zotero search can be broad.
    # We will refine by checking collection and ASIN.
    # Note: Zotero's basic search ('q') searches all fields.
    # We'll try to find by title and then verify ASIN from extra field
    
    # existing_items = zot_client.everything(zot_client.items(q=title, itemType='book', collectionID=collection_id))
    # The above line might be too broad or inefficient.
    # Let's get items in the collection and then filter.
    collection_items = zot_client.collection_items(collection_id, itemType='book')
    
    # The zot_client.collection_items might return a list of full item dicts or summaries.
    # We need to ensure we are working with full item data for the 'extra' field.
    # However, for an initial check, the summary data might be sufficient if 'extra' is included.
    # If not, a zot_client.item(item_key) call would be needed for each.
    # For performance, let's assume 'extra' is often in the summary data from collection_items.

    for item_summary in collection_items:
        # Ensure item_summary is a dict and has 'data'
        if not isinstance(item_summary, dict) or 'data' not in item_summary:
            continue

        item_data = item_summary.get('data', {})
        item_title = item_data.get('title', '')
        item_extra = item_data.get('extra', '') # 'extra' might not always be in summary
        item_key = item_summary.get('key')

        # If 'extra' is not in the summary, we might need to fetch the full item.
        # This is a common pattern with the Zotero API.
        # For now, we proceed if item_extra is None and asin is also None/empty,
        # or if item_extra is present for comparison.
        # A more robust check fetches the full item if item_extra is missing and asin is relevant.
        
        if item_title == title:
            # If ASIN is provided, we must match it in the extra field.
            if asin and asin != "UnknownASIN":
                if item_extra and f"ASIN: {asin}" in item_extra:
                    print(f"  Found existing Zotero book item for '{title}' (ASIN: {asin}) with key: {item_key}")
                    # Fetch the full item to ensure we return consistent data structure
                    return zot_client.item(item_key) if item_key else item_summary
                # If ASIN is provided but not found in extra, this is not a match.
                # However, if item_extra was not available in summary, we *could* fetch full item here to check.
                # For simplicity, we'll assume if ASIN is critical, 'extra' should be checked.
            else: # No ASIN provided or it's an "UnknownASIN", so title match is enough
                print(f"  Found existing Zotero book item for '{title}' (No specific ASIN match required) with key: {item_key}")
                return zot_client.item(item_key) if item_key else item_summary


    # If not found, create it
    print(f"  Book item '{title}' (ASIN: {asin}) not found in Zotero collection. Creating new item...")
    template = zot_client.item_template('book')
    template['title'] = title
    
    # Revised author handling
    processed_creators = []
    if author and author.strip() and author != "Unknown Author":
        names = author.split()
        first_name = ""
        last_name = ""

        if len(names) == 1:
            # If there's only one name part, Zotero prefers it in lastName or as a single 'name' field.
            # Using lastName for a single name is a common convention for firstName/lastName pairs.
            last_name = names[0]
        elif len(names) > 1:
            first_name = names[0]
            last_name = " ".join(names[1:])

        # Add creator if we have valid name parts
        if first_name or last_name: 
            processed_creators.append({
                'creatorType': 'author',
                'firstName': first_name,
                'lastName': last_name
            })
        elif author.strip(): # Fallback to 'name' if splitting resulted in empty parts but author string is not empty
            processed_creators.append({
                'creatorType': 'author',
                'name': author.strip()
            })
    
    # If after parsing, processed_creators is empty (e.g., author was None, empty, or "Unknown Author")
    # or parsing failed to produce valid parts, use a default or the provided author string as 'name'.
    if not processed_creators:
        # Use the original author string if it's not empty/None, otherwise default to "Unknown Author"
        name_to_use = author.strip() if (author and author.strip()) else "Unknown Author"
        processed_creators.append({
            'creatorType': 'author',
            'name': name_to_use
        })
        
    template['creators'] = processed_creators # Assign the new list, overwriting template default

    # Add ASIN to the 'extra' field for future identification and to help with manual data fixup
    extra_field_content = []
    if asin and asin != "UnknownASIN":
        extra_field_content.append(f"ASIN: {asin}")
    # Could add "Imported from Kindle Highlights Scraper" here too
    extra_field_content.append("Source: Kindle Highlights Scraper")
    template['extra'] = "\n".join(extra_field_content)
    
    template['collections'] = [collection_id] # Add to our target collection

    try:
        resp = zot_client.create_items([template])
        if resp['successful']: # Note: create_items returns 'successful', not 'success' like create_collections
            # The response for create_items gives a dict where keys are item indices (e.g., '0')
            # and values are dicts containing the 'key' and 'version' of the created item.
            created_item_info = list(resp['successful'].values())[0] 
            new_item_key = created_item_info['key']
            # Fetch the full item data as create_items only returns a summary
            new_item_data = zot_client.item(new_item_key)
            print(f"  Successfully created Zotero book item for '{title}' with key: {new_item_data['key']}")
            return new_item_data
        else:
            print(f"  Failed to create Zotero item for '{title}'. Response: {resp}")
            # Log details if available in 'failed' part of response
            if resp.get('failed'):
                for k, v in resp['failed'].items():
                    print(f"    Failure reason for item index {k}: {v.get('message', 'No message')}, Code: {v.get('code', 'N/A')}")
            return None
    except Exception as e:
        print(f"  Error creating Zotero item for '{title}': {e}")
        return None

def add_note_to_item(zot_client, parent_item_key, note_content, item_type, original_db_id):
    """Creates a Zotero note and attaches it to the parent item."""
    template = zot_client.item_template('note')
    # Zotero notes are HTML. Basic formatting for readability.
    html_note_content = f"<p><em>Kindle {item_type.capitalize()}</em></p><p>{note_content.replace('\n', '<br>')}</p>"
    # Removed appending original_id to the note content itself
    template['note'] = html_note_content
    template['parentItem'] = parent_item_key
    template['tags'] = [{'tag': 'Kindle Import'}]
    
    try:
        resp = zot_client.create_items([template])
        if resp['successful']:
            return True
        else:
            print(f"    Failed to create note. Response: {resp}")
            if resp.get('failed'):
                for k, v in resp['failed'].items():
                    print(f"      Failure reason for note (original_id: {original_db_id}): {v.get('message', 'No message')}, Code: {v.get('code', 'N/A')}")
            return False
    except Exception as e:
        print(f"    Error creating Zotero note (original_id: {original_db_id}): {e}")
        return False

if __name__ == "__main__":
    main()
