import mwclient  # for downloading example Wikipedia articles
import warnings
import urllib3
import json
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor

# Suppress only the specific Unverified HTTPS request warning
warnings.filterwarnings('ignore', 'Unverified HTTPS request is being made.*',
                        urllib3.exceptions.InsecureRequestWarning)

WIKI_SITE = "wiki.project1999.com"
site = mwclient.Site(host=WIKI_SITE, reqs={"verify": False}, path="/")

    


def import_title(page):
    conn = sqlite3.connect('metadata.db')
    c = conn.cursor()

    title = page.name
    c.execute('SELECT title FROM metadata WHERE title = ?', (title,))
    if c.fetchone() is not None:
        conn.close()
        return

    print(f"Processing: {title}...")
    try:
        categories = [category.name for category in page.categories()]
        backlinks = [linked_page.name for linked_page in page.backlinks()]
        links = [linked_page.name for linked_page in page.links()]

        # Download the content of the page
        content = page.text()

        # Insert the data into the metadata table
        c.execute('''
            INSERT OR REPLACE INTO metadata VALUES (?, ?, ?, ?, ?)
        ''', (title, json.dumps(categories), json.dumps(backlinks), json.dumps(links), content))
        conn.commit()

    except Exception as e:
        print(f"Failed to process {title}: {e}")

    conn.close()

with ThreadPoolExecutor(max_workers=24) as executor:
    # Process all pages
    all_pages = []
    all_pages += [page for page in site.allpages(namespace=-1)] # Special namespace
    # all_pages += [page for page in site.allpages(namespace=0)]
    # all_pages += [page for page in site.allpages(namespace=2)]   # User namespace
    # all_pages += [page for page in site.allpages(namespace=4)]   # Project namespace
    # all_pages += [page for page in site.allpages(namespace=6)]   # File namespace
    # all_pages += [page for page in site.allpages(namespace=8)]   # MediaWiki namespace
    # all_pages += [page for page in site.allpages(namespace=10)]  # Template namespace
    # all_pages += [page for page in site.allpages(namespace=12)]  # Help namespace
    # all_pages += [page for page in site.allpages(namespace=14)]  # Category namespace
    
    for page in all_pages:
        executor.submit(import_title, page)