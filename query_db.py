import sqlite3
import pandas as pd

DB_NAME = "kindle_highlights.sqlite"
TABLE_NAME = "highlights_notes"

def run_queries():
    conn = None  # Initialize conn to None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        print(f"--- Querying Database: {DB_NAME} ---")

        # 1. Total count of records
        cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        total_count = cursor.fetchone()[0]
        print(f"\n1. Total records in '{TABLE_NAME}': {total_count}")

        # 2. Count by item_type
        print("\n2. Records by item_type:")
        cursor.execute(f"SELECT item_type, COUNT(*) FROM {TABLE_NAME} GROUP BY item_type")
        for row in cursor.fetchall():
            print(f"   - {row[0]}: {row[1]}")

        # 3. Show 5 most recent highlights
        print("\n3. Last 5 highlights added (content might be truncated for display):")
        # Using pandas for nicer table display for this one
        try:
            df_highlights = pd.read_sql_query(f"SELECT book_title, book_author, item_type, content, original_id, retrieved_at FROM {TABLE_NAME} WHERE item_type = 'highlight' ORDER BY retrieved_at DESC LIMIT 5", conn)
            if not df_highlights.empty:
                for index, row in df_highlights.iterrows():
                    print(f"    Book: {row['book_title']} by {row['book_author']}\n    Content: {row['content'][:100] + '...' if len(row['content']) > 100 else row['content']}\n    Retrieved: {row['retrieved_at']}\n    ---------------------")
            else:
                print("   No highlights found.")
        except Exception as e:
            print(f"   Error fetching highlights with pandas: {e}")
            print("   Falling back to simple cursor fetch for highlights:")
            cursor.execute(f"SELECT book_title, book_author, content, retrieved_at FROM {TABLE_NAME} WHERE item_type = 'highlight' ORDER BY retrieved_at DESC LIMIT 5")
            highlights_fallback = cursor.fetchall()
            if highlights_fallback:
                for row_fb in highlights_fallback:
                    print(f"    Book: {row_fb[0]} by {row_fb[1]}\n    Content: {row_fb[2][:100] + '...' if len(row_fb[2]) > 100 else row_fb[2]}\n    Retrieved: {row_fb[3]}\n    ---------------------")
            else:
                print("   No highlights found (fallback).")


        # 4. Show 5 most recent notes
        print("\n4. Last 5 notes added (content might be truncated for display):")
        try:
            df_notes = pd.read_sql_query(f"SELECT book_title, book_author, item_type, content, original_id, retrieved_at FROM {TABLE_NAME} WHERE item_type = 'note' ORDER BY retrieved_at DESC LIMIT 5", conn)
            if not df_notes.empty:
                for index, row in df_notes.iterrows():
                    print(f"    Book: {row['book_title']} by {row['book_author']}\n    Content: {row['content'][:100] + '...' if len(row['content']) > 100 else row['content']}\n    Retrieved: {row['retrieved_at']}\n    ---------------------")
            else:
                print("   No notes found.")
        except Exception as e:
            print(f"   Error fetching notes with pandas: {e}")
            print("   Falling back to simple cursor fetch for notes:")
            cursor.execute(f"SELECT book_title, book_author, content, retrieved_at FROM {TABLE_NAME} WHERE item_type = 'note' ORDER BY retrieved_at DESC LIMIT 5")
            notes_fallback = cursor.fetchall()
            if notes_fallback:
                for row_fb in notes_fallback:
                    print(f"    Book: {row_fb[0]} by {row_fb[1]}\n    Content: {row_fb[2][:100] + '...' if len(row_fb[2]) > 100 else row_fb[2]}\n    Retrieved: {row_fb[3]}\n    ---------------------")
            else:
                print("   No notes found (fallback).")


        # 5. Check for items with no content (should be 0 if scraper works correctly)
        cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE content IS NULL OR content = ''")
        empty_content_count = cursor.fetchone()[0]
        print(f"\n5. Records with empty or NULL content: {empty_content_count}")

        # 6. Check for duplicate original_id (should be 0 if UNIQUE constraint works)
        # This query is a bit more complex: counts groups of original_id having more than one entry.
        cursor.execute(f"SELECT COUNT(*) FROM (SELECT original_id FROM {TABLE_NAME} GROUP BY original_id HAVING COUNT(*) > 1)")
        duplicate_original_id_groups = cursor.fetchone()[0]
        print(f"\n6. Number of original_id groups with duplicates: {duplicate_original_id_groups}")

        # 7. List unique authors and their book counts
        print("\n7. Authors and their book counts (based on entries in highlights_notes):")
        try:
            # This query counts distinct book titles per author.
            # It assumes that each entry for a book_title will have the same book_author.
            cursor.execute(f"SELECT book_author, COUNT(DISTINCT book_title) as num_books FROM {TABLE_NAME} WHERE book_author IS NOT NULL AND book_author != 'Unknown Author' GROUP BY book_author ORDER BY num_books DESC, book_author ASC")
            authors_books = cursor.fetchall()
            if authors_books:
                for row_ab in authors_books:
                    print(f"   - {row_ab[0]}: {row_ab[1]} book(s)")
            else:
                print("   No author information found or all authors are 'Unknown Author'.")
        except Exception as e:
            print(f"   Error fetching author book counts: {e}")


    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_queries() 