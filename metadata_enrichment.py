import re
import requests
from bs4 import BeautifulSoup, Tag
from typing import Optional, Dict

def extract_asin(extra: str) -> Optional[str]:
    """Extract ASIN from the extra field."""
    match = re.search(r"ASIN: ([A-Z0-9]{10})", extra)
    return match.group(1) if match else None

def get_book_metadata_by_title(title: str, author: str) -> Optional[Dict]:
    """Get book metadata from Google Books API using title and author."""
    import re
    clean_title = re.sub(r'\s*\([^)]*\)', '', title)
    query = f"intitle:{clean_title}+inauthor:{author}"
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()
    if not data.get("items"):
        return None
    book = data["items"][0]["volumeInfo"]
    metadata = {
        "ISBN": book.get("industryIdentifiers", [{}])[0].get("identifier", ""),
        "publisher": book.get("publisher", ""),
        "date": book.get("publishedDate", ""),
        "numPages": book.get("pageCount", ""),
        "language": book.get("language", ""),
        "place": "",
        "edition": ""
    }
    return metadata

def get_isbn_from_amazon(asin: str) -> Optional[str]:
    """Get ISBN from Amazon page using ASIN."""
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        details = soup.find('div', {'id': 'detailBullets_feature_div'})
        if details and isinstance(details, Tag):
            for item in details.find_all('li'):
                text = item.get_text().strip()
                if 'ISBN-13' in text:
                    isbn = re.search(r'ISBN-13\s*:\s*([0-9-]+)', text)
                    if isbn:
                        return isbn.group(1).replace('-', '')
        info = soup.find('div', {'id': 'productDetails_feature_div'})
        if info and isinstance(info, Tag):
            for item in info.find_all('tr'):
                text = item.get_text().strip()
                if 'ISBN-13' in text:
                    isbn = re.search(r'ISBN-13\s*:\s*([0-9-]+)', text)
                    if isbn:
                        return isbn.group(1).replace('-', '')
    except Exception:
        pass
    return None

def get_book_metadata_by_isbn(isbn: str) -> Optional[Dict]:
    """Get book metadata from Google Books API using ISBN."""
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()
    if not data.get("items"):
        return None
    book = data["items"][0]["volumeInfo"]
    metadata = {
        "ISBN": isbn,
        "publisher": book.get("publisher", ""),
        "date": book.get("publishedDate", ""),
        "numPages": book.get("pageCount", ""),
        "language": book.get("language", ""),
        "place": "",
        "edition": ""
    }
    return metadata

def enrich_book_metadata(title: str, author: str, asin: str) -> Optional[Dict]:
    """Enrich book metadata by extracting ISBN from Amazon using ASIN, then querying Google Books API."""
    if not asin:
        return None
    isbn = get_isbn_from_amazon(asin)
    if isbn:
        metadata = get_book_metadata_by_isbn(isbn)
        if metadata:
            return metadata
    return None
