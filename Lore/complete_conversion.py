import requests
import json
import mwclient
from bs4 import BeautifulSoup, NavigableString, Tag
import re
from IPython.display import display, HTML

from bs4 import BeautifulSoup
import pandas as pd
import json
from io import StringIO
import sqlite3


def get_random_page():
    S = requests.Session()

    URL = "http://localhost/mediawiki/api.php"  # replace with your wiki's API URL

    # Step 1: Retrieve a login token
    LOGIN_TOKEN = S.get(url=URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()['query']['tokens']['logintoken']

    # Step 2: Send a post request to log in. 
    LOGIN_R = S.post(URL, data={
        "action": "login",
        "lgname": "renobot",
        "lgpassword": "sakura1010",
        "lgtoken": LOGIN_TOKEN,
        "format": "json"
    })

    # Step 3: Get a random page
    RANDOM_R = S.get(url=URL, params={
        "action": "query",
        "list": "random",
        "rnnamespace": 0,
        "rnlimit": 1,
        "format": "json"
    })

    random_page = RANDOM_R.json()['query']['random'][0]['title']

    # Step 4: Parse the text of the random page
    PARSE_R = S.get(url=URL, params={
        "action": "parse",
        "page": random_page,
        "prop": "text",
        "disabletoc": 1,  # Disable the Table of Contents
        "formatversion": 2,
        "format": "json"
    })

    parsed_text = PARSE_R.json()['parse']['text']

    return(random_page, parsed_text)


def get_specific_page(title_name):
    S = requests.Session()
    URL = "http://localhost/mediawiki/api.php"  # replace with your wiki's API URL
    # Step 1: Retrieve a login token
    LOGIN_TOKEN = S.get(url=URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()['query']['tokens']['logintoken']

    # Step 2: Send a post request to log in. 
    LOGIN = S.post(URL, data={
        "action": "login",
        "lgname": "renobot",
        "lgpassword": "sakura1010",
        "lgtoken": LOGIN_TOKEN,
        "format": "json"
    })

    PARSE_R = S.get(url=URL, params={
        "action": "parse",
        "page": title_name,
        "prop": "text",
        "disabletoc": 1,  # Disable the Table of Contents
        "formatversion": 2,
        "format": "json"
    })
    
    
    parsed_text = PARSE_R.json()['parse']['text']

    return(title_name, parsed_text)

def get_all_pages_excluding():
    categories_to_exclude = ["Non-P99 Content", "Articles for Deletion"]
    templates_to_exclude = ["DNE","Luclin"]
    pages_linking_to_exclude = ["Does Not Exist"]

    S = requests.Session()
    URL = "http://localhost/mediawiki/api.php"  # replace with your wiki's API URL

    # Step 1: Retrieve a login token
    LOGIN_TOKEN = S.get(url=URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()['query']['tokens']['logintoken']

    # Step 2: Send a post request to log in. Use a loop to handle the possible need for a second request
    login_data = {
        "action": "login",
        "lgname": "ryandward",
        "lgpassword": "sakura1010",
        "lgtoken": LOGIN_TOKEN,
        "format": "json"
    }
    while True:
        LOGIN = S.post(URL, data=login_data)
        print(LOGIN.json())  # Add this line
        login_result = LOGIN.json()['login']['result']
        if login_result == 'Success':
            break
        elif login_result == 'NeedToken':
            login_data['lgtoken'] = LOGIN.json()['login']['token']
        else:
            raise ValueError(f'Login failed: {login_result}')

    # Open the file in write mode, which will blank it
    with open('Lore/valid_pages.json', 'w') as f:
        pass

    filtered_pages = []
    apcontinue = ''
    while True:
        # Step 3: Get all pages
        ALL_PAGES = S.get(url=URL, params={
            "action": "query",
            "list": "allpages",
            "aplimit": 50,  # Increase this to get more pages
            "apcontinue": apcontinue,
            "apfilterredir": "nonredirects",  # Add this line
            "format": "json"
        }).json()

        # Filter pages
        for page in ALL_PAGES['query']['allpages']:
            print(f"Processing page: {page['title']}")  # Add this line

            # Get the categories, templates, and links of the page
            response = S.get(url=URL, params={
                "action": "query",
                "prop": "categories|templates|links",
                "titles": page['title'],
                "format": "json"
            }).json()

            # Get the page info from the response
            PAGE_INFO = list(response['query']['pages'].values())[0]

            # Check if the page should be excluded
            categories = [cat['title'] for cat in PAGE_INFO.get('categories', [])]
            templates = [temp['title'] for temp in PAGE_INFO.get('templates', [])]
            links = [link['title'] for link in PAGE_INFO.get('links', [])]
            if (any(cat in categories_to_exclude for cat in categories) or
                any(temp in templates_to_exclude for temp in templates) or
                any(link in pages_linking_to_exclude for link in links) or
                any(cat.startswith('Fashion') for cat in categories) or
                any(cat.startswith('Patch') for cat in categories)):

                print(f"Excluding page: {page['title']}")  # Add this line
                continue

            # Add the page to the filtered list
            filtered_pages.append(page)

        # Write the filtered pages to the file after each batch
        with open('Lore/valid_pages.json', 'a') as f:
            for page in filtered_pages:
                f.write(json.dumps(page) + '\n')

        # Clear the filtered pages list for the next batch
        filtered_pages.clear()

        # If we've processed all pages, break the loop
        if 'continue' not in ALL_PAGES:
            break

        # Otherwise, update the apcontinue parameter for the next iteration
        apcontinue = ALL_PAGES['continue']['apcontinue']

    # Write any remaining filtered pages to the file after the loop
    with open('Lore/valid_pages.json', 'a') as f:
        for page in filtered_pages:
            f.write(json.dumps(page) + '\n')

    return filtered_pages

def cleanup_everything(title_name, wiki_html):

    print(f"Processing {title_name}...")

    def adjust_headings(soup, title_name):
        # Find all headings
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9'])

        # Remove any headings that are completely blank
        for heading in headings:
            if heading.get_text(strip=True) == '':
                heading.decompose()

        # Get the unique heading levels in the original document
        original_levels = sorted(set(int(heading.name[1]) for heading in headings))

        # Create a mapping from the original levels to the new levels
        level_mapping = {original_level: i + 2 for i, original_level in enumerate(original_levels)}

        # Adjust the heading levels according to the mapping
        for heading in headings:
            original_level = int(heading.name[1])
            new_level = level_mapping[original_level]
            heading.name = 'h' + str(min(6, new_level))  # HTML only supports up to h6

        # Create a new h1 heading with the title name
        new_heading = soup.new_tag('h1')
        new_heading.string = title_name
        soup.insert(0, new_heading)

        # Update the headings list after the adjustment
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9'])

        return soup, headings

    def flatten_headings(soup, headings):
        heading_stack = []

        for heading in headings:
            level = int(heading.name[1])
            text = heading.get_text(strip=True)

            # Pop from the stack if the current level is less than or equal to the top level in the stack
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()

            # Add the current heading to the stack
            if heading_stack:
                # Only append the text of the last heading in the stack if it's of a higher level
                text = heading_stack[-1][1] + ': ' + text if heading_stack[-1][0] > level else text
            heading_stack.append((level, text))

            # Replace the text of the heading in the soup
            heading.string.replace_with(NavigableString(text))

        return soup

    def unwrap_stylistic_elements(fixed_html):
        soup = BeautifulSoup(fixed_html, 'html.parser')

        stylistic_tags = ['b', 'strong', 'i', 'em', 'mark', 'small', 'del', 'ins', 'sub', 'sup']

        for tag in stylistic_tags:
            for match in soup.findAll(tag):
                match.unwrap()

        s_tag = soup.find('s')
        if s_tag:
            s_tag.decompose()

        return str(soup)

    def prepend_parent_heading(soup, headings):
        # Initialize an empty stack to keep track of the parent headings
        stack = []

        # Iterate over the headings
        for heading in headings:
            # Get the level of the current heading
            level = int(heading.name[1])

            # If the stack is not empty and the level of the current heading is less than or equal to the level of the heading at the top of the stack
            while stack and level <= int(stack[-1].name[1]):
                # Pop the heading from the stack
                stack.pop()

            # If the stack is not empty
            if stack:
                # Prepend the text of the heading at the top of the stack to the current heading
                heading.string = stack[-1].get_text(strip=True) + ' - ' + heading.get_text(strip=True)

            # Push the current heading onto the stack
            stack.append(heading)

        return soup


    soup = BeautifulSoup(wiki_html, 'html.parser')

    # Remove all 'img' tags
    for img in soup.find_all('img'):
        img.decompose()

    for s_tag in soup.find_all('s'):
        s_tag.decompose()
    
    pre_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9'])
    # print("Before: ", pre_headings)
    soup, headings = adjust_headings(soup, title_name)
    # soup = flatten_headings(soup, headings)
    # print(soup)
    # print("After: ", headings)

    soup = prepend_parent_heading(soup, headings)
    # soup = unwrap_stylistic_elements(str(soup))
    # print(soup)

    # Remove everything between h1 and the first instance of text like this __text__
    soup = re.sub(r'<h1>(.*?)</h1>(.*?)__(.+?TOC)__', r'<h1>\1</h1>\2', str(soup), flags=re.DOTALL)
    # Remove everything between __NOEDITSECTION__ and the end
    soup = re.sub(r'__NOEDITSECTION__(.*?)', r'', str(soup), flags=re.DOTALL)

    # strip html comments
    soup = re.sub(r'<!--(.*?)-->', r'', str(soup), flags=re.DOTALL)

    soup = "<html><body>" + str(soup) + "</body></html>"

    soup = BeautifulSoup(soup, 'html.parser')
    # print(soup)

    html_text = str(soup)


    def prepend_star_to_li(element):
        # If the element is a 'li' tag, prepend a '*' to its text
        if element.name == 'li':
            element.string = '* ' + element.get_text()

        # If the element has children, apply the function to each child
        for child in element.children:
            if hasattr(child, 'children'):
                prepend_star_to_li(child)

    # Apply the function to the table

    def table_to_json(table):
        #unwrap tbody
        if table.find('tbody'):
            table.find('tbody').unwrap()

        # prepend_star_to_li(table)
        tr_elements = table.find_all('tr')
        td_elements = table.find_all('td')
        th_elements = table.find_all('th')

        n_th = len(table.find_all('th'))
        n_td = len(table.find_all('td'))
        n_tr = len(table.find_all('tr'))

        all_rows_have_th = all(tr.find('th') is not None for tr in tr_elements)
        # do some rows outside the table have th
        outside_th = any(tr.find('th') is not None for tr in tr_elements[1:])    

        if n_th == 0 and n_td > 2 and n_tr == 2:
            # change the first td to th and recusrively call the function
            table.find_all('td')[0].name = 'th'
            return table_to_json(table)
        
        # if n_th == 0 and n_td == 2 and n_tr > 2:
        #     #transpose the table
        #     table_html = str(table)
        #     df = pd.read_html(StringIO(table_html))[0]  # Convert the table to a DataFrame
        #     df_transposed = df.T  # Transpose the DataFrame
        #     table = df_transposed.to_html() # convert back to html

        elif n_th == 0:
            table_str = str(table)
            # replace \n with space
            table_str = re.sub(r'\n', r' ', table_str)

            # Convert the modified string back into a BeautifulSoup object
            soup = BeautifulSoup(table_str, 'html.parser')

            # Find the modified table in the BeautifulSoup object
            table = soup.find('table')

            # Convert the modified table into a pandas DataFrame and then into a list of lists
            try:
                table_list = pd.read_html(StringIO(str(table)))[0].values.tolist()

            except:
                print(f"Error processing table: {table}")
                exit()
            # Remove duplicate values from each row while preserving the original order
            table_list = [list(dict.fromkeys(row)) for row in table_list]

            # Convert the list of lists into a JSON array
            json_table = json.dumps(table_list)

            return json_table
        
        elif all_rows_have_th:
            # Find all 'tr' elements in the table
            tr_elements = table.find_all('tr')

            # Create a dictionary where the key is the 'th' element in each row
            # and the value is an array of the 'td' elements in the row
            td_dict = {tr.find('th').text.strip(): [td.text.strip() for td in tr.find_all('td')] for tr in tr_elements}
            return td_dict
        
        elif outside_th:
            # Find all 'tr' elements in the table
            tr_elements = table.find_all('tr')

            # Create a list to store the tables
            tables = []

            # Create a list to store the current group of rows
            current_rows = []

            # Iterate over the 'tr' elements
            for tr in tr_elements:
                # If the 'tr' element contains a 'th' element and 'current_rows' is not empty,
                # create a new table from 'current_rows' and add it to 'tables'
                if tr.find('th') is not None and current_rows:
                    new_table = BeautifulSoup('<table>' + ''.join(str(tr) for tr in current_rows) + '</table>', 'html.parser')
                    tables.append(new_table)
                    current_rows = []

                # Add the 'tr' element to 'current_rows'
                current_rows.append(tr)

            # If 'current_rows' is not empty after iterating over all 'tr' elements,
            # create a new table from 'current_rows' and add it to 'tables'
            if current_rows:
                new_table = BeautifulSoup('<table>' + ''.join(str(tr) for tr in current_rows) + '</table>', 'html.parser')
                tables.append(new_table)

            results = []
            # Process each table separately

            for new_table in tables:
                table_df = pd.read_html(StringIO(str(new_table)))[0]
                table_json = table_df.to_dict(orient='records')
                results.extend(table_json)
            return json.dumps(results)

            # Remove the original table from the soup
        
        else:
            json_table = json.dumps(pd.read_html(StringIO(str(table)))[0].to_dict(orient='records'))
            return json_table
        
    

    html_soup = BeautifulSoup(html_text, 'html.parser')
    # Replace non-breaking spaces with regular spaces in the entire document
    html_soup = BeautifulSoup(str(html_soup).replace('\u00a0', ' '), 'html.parser')

    all_tables = html_soup.find_all('table')
    processed_tables = []  # List to keep track of processed tables

    for table in all_tables:
        # make sure the table has text if not, decompose
        if not any(isinstance(descendant, NavigableString) and descendant.strip() != '' for descendant in table.descendants):
            table.decompose()
            continue
        # Add this check to ensure the table contains td or th elements
        if not any(table.find(tag_name) for tag_name in ['td', 'th']):
            table.decompose()
            continue
        tbody = table.find('tbody')
        # print(table)
        table_html = str(table)
        processed_table = table_to_json(table)
        # print(processed_table)
        # replace the table with the processed table in the html_soup
        # try:
        table.replace_with(BeautifulSoup("\n" + str(processed_table) +"\n", 'html.parser'))
        # except Exception as e:
        #     print(e)
        #     continue

    import html2text
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.ignore_emphasis = True
    h.ignore_tables = True
    # h.unicode_snob = True  # Don't escape unicode characters
    h.body_width = 0
    h.wrap_links = False
    text = h.handle(str(html_soup))

    #delete lines that contain only the title_name
    # text = re.sub(rf'^{title_name}$', r'', text, flags=re.MULTILINE)

    #remove double line breaks
    # Split the text into lines, strip each line, and filter out empty lines
    lines = [line.strip() for line in text.split('\n\n') if line.strip()]

    # Join the lines back together with two newlines
    text = '\n\n'.join(lines)

    # convert ## to == text ==
    def replace_hash_with_equal(match):
        hash_count = match.group(0).count('#')
        return '=' * hash_count + ' ' + match.group(1) + ' ' + '=' * hash_count

    text = re.sub(r'^#{1,10} (.*)', replace_hash_with_equal, text, flags=re.MULTILINE)
    # get rid of [edit]
    text = re.sub(r'\[edit\]', r'', text, flags=re.MULTILINE)

    print(f"Finished processing {title_name}...")
    return(text)


    
# Update the metadata.db with the pageids from the valid_pages.json file
    
def update_page_ids():
    with open('Lore/valid_pages.json', 'r') as f:
        all_pages = [json.loads(line) for line in f]

    # print(all_pages)


    db_path = "metadata.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # It already exists, so just add it where conditions match
    for page in all_pages:
        print(f"Processing: {page['title']}...")
        title = page['title']
        pageid = page['pageid']
        cur.execute('UPDATE metadata SET pageid = ? WHERE title = ?', (pageid, title))
        conn.commit()

    conn.close()

def load_valid_pages():
    with open('Lore/valid_pages.json', 'r') as f:
        all_pages = [json.loads(line) for line in f]

    return all_pages


# FUNCTION CALL AREA################################
# all_pages = get_all_pages_excluding()
# title_name, wiki_html = get_random_page()
# title_name, wiki_html = get_specific_page("Monk")
# cleanup_everything(title_name, wiki_html)
# update_page_ids()
####################################################


# for the first 10 valid pages. perform the cleanup_everything function

all_pages = load_valid_pages()
for page in all_pages[:10]:
    title_name, wiki_html = get_specific_page(page['title'])
    cleanup_everything(title_name, wiki_html)


# insert the cleaned up html into the metadata.db as markdown on metadata.markdown where pageid = page['pageid']

db_path = "metadata.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# It already exists, so just add it where conditions match
# perform cleanup_everything on the first 10 valid pages and then insert the cleaned up html into the metadata.db as markdown on metadata.markdown where pageid = page['pageid']

for page in all_pages:
    title_name, wiki_html = get_specific_page(page['title'])
    cleaned_up_html = cleanup_everything(title_name, wiki_html)
    pageid = page['pageid']
    cur.execute('UPDATE metadata SET markdown = ? WHERE pageid = ?', (cleaned_up_html, pageid))
    conn.commit()