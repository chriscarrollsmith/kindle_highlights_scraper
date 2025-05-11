# Kindle Highlights Scraper

## Description

This Python script scrapes your Kindle highlights and notes from the Amazon Kindle Notebook webpage (`https://read.amazon.com/notebook`). It uses Playwright to automate browser interaction, extracts your annotations, and saves them locally into an SQLite database and a Parquet file.

The script is designed to handle initial login by saving authentication state, and then use this saved state for subsequent headless scraping runs.

## Features

*   Automated scraping of Kindle highlights and notes.
*   Persistent login using Playwright's authentication state saving.
*   Saves data to an SQLite database for easy querying.
*   Saves data to a Parquet file for use with data analysis tools.
*   Detects and reports books that may have export limits imposed by Amazon.
*   Attempts to extract book ASINs.
*   Basic error handling and timeout management.

## Prerequisites

*   Python 3.8+
*   `uv` (Python packaging tool, can be installed via `pip install uv`)

## Setup and Installation

1.  **Clone the repository (or download the files):**
    ```bash
    # If this were a git repo:
    # git clone <repository-url>
    # cd kindle-highlights-scraper
    ```
    For now, ensure you have `scraper.py` in your project directory.

2.  **Create a virtual environment and install dependencies:**
    This project uses `uv` for environment and package management.
    ```bash
    # Create and activate a virtual environment
    uv venv
    source .venv/bin/activate  # On Linux/macOS
    # .venv\Scripts\activate    # On Windows

    # Install required packages
    uv pip install playwright pandas sqlalchemy pyarrow
    ```

3.  **Install Playwright browser binaries:**
    Playwright needs browser binaries to operate. After installing the `playwright` package, run:
    ```bash
    uv run playwright install
    ```
    This will download the necessary browser (Chromium by default).

## Usage

1.  **First-time Run (Login):**
    When you run the script for the first time, it will detect that no authentication state (`auth_state.json`) exists.
    ```bash
    uv run python scraper.py
    ```
    A browser window will open, and you'll be prompted to:
    *   Navigate to `https://read.amazon.com/notebook`.
    *   Log in with your Amazon account.
    *   Ensure you are on the Kindle Notebook page where your books and highlights are visible.
    *   Once logged in and on the correct page, press **Enter** in the terminal where the script is running.
    The script will save your authentication state to `auth_state.json` and then exit, prompting you to re-run it.

2.  **Subsequent Runs (Scraping):**
    After the `auth_state.json` file is created, subsequent runs will use this saved state to log in automatically and proceed with scraping.
    ```bash
    uv run python scraper.py
    ```
    The script will run headlessly (no browser window visible by default), navigate to your Kindle Notebook, and scrape the highlights and notes for each book.

    *   **Output:**
        *   Data will be saved to `kindle_highlights.sqlite` (SQLite database).
        *   Data will also be saved to `kindle_highlights.parquet` (Parquet file).
        *   A summary will be printed to the console, including any books for which export limits were detected.

## How It Works

The script uses the Playwright library to control a web browser.
1.  It navigates to the Kindle Notebook URL.
2.  It uses pre-defined CSS selectors to identify:
    *   The list of your books.
    *   The title and ASIN (or other ID) for each book.
    *   The individual highlight and note elements.
    *   The text content of each highlight and note.
3.  It clicks through each book, waits for its content to load, and then extracts the annotations.
4.  The collected data is stored in a Pandas DataFrame and then written to the SQLite database and Parquet file.

**Important Note on Selectors:** Web pages change. If Amazon updates the structure of the Kindle Notebook page, the CSS selectors in `scraper.py` (e.g., `BOOK_LIST_SELECTOR`, `HIGHLIGHT_SELECTOR`) might need to be updated. Refer to the comments in the script and use your browser's developer tools to find the new selectors if the script stops working correctly.

## Data Storage

*   **SQLite Database (`kindle_highlights.sqlite`):**
    *   Table name: `highlights_notes`
    *   Columns: `id`, `book_title`, `book_asin`, `item_type` ('highlight' or 'note'), `content`, `original_id` (UNIQUE), `location`, `date_created`, `retrieved_at`.
    *   The `original_id` is used to prevent duplicate entries on subsequent runs.
*   **Parquet File (`kindle_highlights.parquet`):**
    *   Contains the same data as the SQLite table, useful for big data processing or loading into other analytical tools.

## Troubleshooting

*   **Script doesn't find books/highlights:**
    *   The most common issue is outdated CSS selectors. Amazon might have updated their website. You'll need to inspect the page elements using browser developer tools (F12) and update the `*_SELECTOR` constants in `scraper.py`.
    *   Ensure you are successfully logged in during the initial `auth_state.json` creation and that you are on the main notebook page.
*   **Login issues / `auth_state.json` not working:**
    *   Delete `auth_state.json` and re-run the script to go through the manual login process again.
    *   Amazon might have changed its login flow or session management in a way that invalidates the saved state more quickly.
*   **Timeout errors:**
    *   If you have a slow internet connection or many books/highlights, you might encounter timeouts. You can try increasing the timeout values in `scraper.py` (e.g., `timeout=90000` in `page.goto`, or timeouts in `wait_for_selector`).

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change. Please make sure to update tests as appropriate (if any are added).

## License

[MIT](https://choosealicense.com/licenses/mit/) (You can choose any license you prefer)
