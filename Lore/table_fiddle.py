# import html
# import json
import random
import re
import sqlite3
import string
from io import StringIO

# import html2text
import mwparserfromhell
import pandas as pd
from bs4 import BeautifulSoup, NavigableString
# from mwparserfromhell.definitions import SINGLE
from pyparsing import Combine, Literal, ParserElement, nestedExpr, originalTextFor
from wikiexpand.expand import ExpansionContext
from wikiexpand.expand.templates import TemplateDict

# Connect to the SQLite database
conn = sqlite3.connect("metadata.db")
cur = conn.cursor()

# Fetch a random page that is not a template
query = (
    "SELECT title, content, categories FROM metadata WHERE title NOT LIKE 'Template:%' AND content NOT LIKE '#REDIRECT%'"
)
cur.execute(query)
rows = cur.fetchall()

random_page = random.choice(rows)
# get page entitled "Magician"

# random_page = [row for row in rows if row[0] == "Steel Breastplate"][0]

title_name = random_page[0]  # Get the title from the random page
wikitext = random_page[1]  # Get the wikitext from the random page
categories = random_page[2]  # Get the categories from the random page

wikicode = mwparserfromhell.parse(wikitext)

# For main pages, remove onlyinclude tags because they are not transcluded
for tag in wikicode.filter_tags():
    #     # if tag.tag == "includeonly":
    #     #     wikicode = tag.contents
    #     #     break
    #     if tag.tag == "onlyinclude":
    #         # Remove the tag and its contents
    #         wikicode.remove(tag)
    if tag.tag == "noinclude":
        # Remove the tag and its contents
        wikicode.remove(tag)


wikitext = str(wikicode)

# Get rid of bold and italic formatting
wikitext = re.sub(r"''+|'''+", "", wikitext)
wikicode = mwparserfromhell.parse(wikitext)

print(f"Processing: {title_name}...")

wikitext = str(wikicode)

# Get all templates
query = "SELECT title, content FROM metadata WHERE title LIKE 'Template:%'"
cur.execute(query)
rows = cur.fetchall()


# Add each template to the TemplateDict
# Create a standard Python dictionary
temp_dict = {}

# First pass: Add each template to the dictionary
for row in rows:
    content = row[1]
    # content = re.sub(r'{{\s*special:.*?}}', '', row[1], flags=re.IGNORECASE)

    # get rid of '' and ''' formatting
    content = re.sub(r"''+|'''+", "", content)

    # Yes, we know they're templates, but we don't want to include the "Template:" prefix
    title = row[0].replace("Template:", "")

    temp_dict[title] = content
    temp_dict[title.lower()] = content

# Second pass: Resolve redirects
for title, content in temp_dict.items():
    if content.strip().upper().startswith("#REDIRECT"):
        redirect_match = re.search(
            r"\[\[Template:(.*?)\]\]", content, flags=re.IGNORECASE
        )
        if redirect_match:
            redirect_title = redirect_match.group(1)
            if redirect_title in temp_dict:
                temp_dict[title] = temp_dict[redirect_title]

# Third pass remove all templates that start with "special: using mwparserfromhell
for title, content in temp_dict.items():
    wikicode = mwparserfromhell.parse(content)
    for template in wikicode.filter_templates():
        if str(template.name).strip().lower().startswith("special:"):
            wikicode.remove(template)
    temp_dict[title] = str(wikicode)


# Populate the TemplateDict with the resolved templates
templates = TemplateDict()
for title, content in temp_dict.items():
    templates[title] = content

ctx = ExpansionContext(templates=templates)

# Parse the expanded wikitext with mwparserfromhell
wikicode = mwparserfromhell.parse(wikitext)

# Convert all templates that start with ":" into links
# for template in wikicode.filter_templates():
#     if str(template.name).strip().startswith(":"):
#         link_text = str(template.name).strip()[1:]
#         wikicode.replace(template, f'[{link_text}]')

# Update the wikitext with the modified wikicode
wikitext = str(ctx.expand(wikicode))

# add a newline before all tables
# wikitext = re.sub(r'(\{\|)', r'\n\n\1', wikitext)

print(wikitext)

# Resolve if statements by removing html content then evaluating


# Modify default whitespace characters to exclude spaces and newlines
ParserElement.setDefaultWhitespaceChars("")

# Define patterns for triple curly braces
triple_curly_open = Combine(Literal("{{{"))
triple_curly_close = Combine(Literal("}}}"))

# Define the grammar for nested content within double curly braces
content = originalTextFor(
    nestedExpr(
        opener="{{#", closer="}}", ignoreExpr=triple_curly_open | triple_curly_close
    )
)

# Get rid of the extraneous html elements that surround headers. This is a terrible design
headings = mwparserfromhell.parse(wikitext).filter_headings()
# soup = BeautifulSoup(wikitext, 'html.parser')
replacement_headings = {}
# for element in soup.find_all():
# element_text_stripped = element.get_text(strip=False)
parsed_templates = content.searchString(str(wikitext))
# Converting nested lists back into strings, preserving newlines and spaces
found_templates = ["".join(item[0]) for item in parsed_templates]

for found_template in found_templates:
    found_template = found_template
    soup_template = BeautifulSoup(found_template, "html.parser")
    template_text = soup_template.get_text(strip=False)
    parsed_template_text = mwparserfromhell.parse(template_text).filter_templates()
    for valid_parsed_template_text in parsed_template_text:
        evaluated_true = ctx.expand(valid_parsed_template_text)
        if found_template in wikitext:
            if found_template == evaluated_true:
                print(f"{found_template} evaluated to itself, deleting...")
                try:
                    wikitext = wikitext.replace(str(found_template), "")
                    assert found_template not in wikitext
                except:
                    print(f"Could not delete {found_template}")
            else:
                print(
                    f"Found and evaluated {found_template}, was turned out to be: '{evaluated_true}'"
                )
                try:
                    wikitext = wikitext.replace(
                        str(found_template), str(evaluated_true)
                    )
                    assert found_template not in wikitext
                except:
                    print(f"Could not replace {found_template} with {evaluated_true}")


# print(parsed_template_text)


def wrap_text_in_html(text):
    soup = BeautifulSoup(text, "html.parser")

    # If the soup doesn't contain any html tags, wrap the entire content in <html>
    if not soup.find("html"):
        return "<html>" + text + "</html>"
    else:
        return str(soup)


# def wiki_node_to_html(node):
#     if isinstance(node, mwparserfromhell.nodes.Text):
#         text = str(node)
#         # Check if the text is already an HTML tag
#         soup = BeautifulSoup(text, "html.parser")
#         if soup.find():
#             return text
#         else:
#             return str(node)
#     if isinstance(node, mwparserfromhell.nodes.Wikilink):
#         print(node.title, type(node))
#         text = str(node.title)
#         # return f'<a href="{text}">{text}</a>'
#         return text
#     elif isinstance(node, mwparserfromhell.nodes.Tag):
#         contents = ''.join(wiki_node_to_html(n) for n in node.contents.nodes)
#         return f'<{node.tag}>{contents}</{node.tag}>'

#     elif isinstance(node, mwparserfromhell.nodes.ExternalLink):
#         text = str(node.title)
#         # return f'<a href="{text}">{text}</a>'
#         return text

#     elif isinstance(node, mwparserfromhell.nodes.Template):
#         text = str(node.name.strip_code().strip(string.punctuation))
#         print(text)
#         # return f'<a href="{text}">{text}</a>'
#         return text

#     elif isinstance(node, mwparserfromhell.nodes.Heading):
#         text = str(node.title.strip())
#         return f'<h{node.level}>{text.strip()}</h{node.level}>'
#         return str(str(node))
#     else:
#         return ''


def wiki_node_to_html(node):
    # check if the node has nodes
    if hasattr(node, "nodes"):
        html = "".join(wiki_node_to_html(n) for n in wikicode.nodes)
        return html
    elif isinstance(node, mwparserfromhell.nodes.Wikilink):
        text = str(node.title)
        return text
    elif isinstance(node, mwparserfromhell.nodes.Tag):
        contents = "".join(wiki_node_to_html(n) for n in node.contents.nodes)
        return f"<{node.tag}>{contents}</{node.closing_tag}>"
    elif isinstance(node, mwparserfromhell.nodes.ExternalLink):
        text = str(node.title)
        return text
    elif isinstance(node, mwparserfromhell.nodes.Template):
        text = str(node.name.strip_code().strip(string.punctuation))
        return text
    elif isinstance(node, mwparserfromhell.nodes.Heading):
        text = str(node.title.strip())
        return f"<h{node.level}>{text.strip()}</h{node.level}>"
    elif isinstance(node, mwparserfromhell.nodes.Text):
        text = str(node)
        # Check if the text is already an HTML tag
        soup = BeautifulSoup(text, "html.parser")
        if soup.find():
            return text
        else:
            return str(node)
    else:
        return ""


# Convert the wikicode to HTML


# wikitext = wrap_text_in_html(wikitext)
wikicode = mwparserfromhell.parse(wikitext)

wikihtml = "".join(wiki_node_to_html(n) for n in wikicode.nodes)


def adjust_headings(soup, title_name):
    # Find all headings
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9"])

    # Remove any headings that are completely blank
    for heading in headings:
        if heading.get_text(strip=True) == "":
            heading.decompose()

    # Get the unique heading levels in the original document
    original_levels = sorted(set(int(heading.name[1]) for heading in headings))

    # Create a mapping from the original levels to the new levels
    level_mapping = {
        original_level: i + 2 for i, original_level in enumerate(original_levels)
    }

    # Adjust the heading levels according to the mapping
    for heading in headings:
        original_level = int(heading.name[1])
        new_level = level_mapping[original_level]
        heading.name = "h" + str(min(6, new_level))  # HTML only supports up to h6

    # Create a new h1 heading with the title name
    new_heading = soup.new_tag("h1")
    new_heading.string = title_name
    soup.insert(0, new_heading)

    # Update the headings list after the adjustment
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9"])

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
            text = (
                heading_stack[-1][1] + ": " + text
                if heading_stack[-1][0] > level
                else text
            )
        heading_stack.append((level, text))

        # Replace the text of the heading in the soup
        heading.string.replace_with(NavigableString(text))

    return soup


soup = BeautifulSoup(wikihtml, "html.parser")

pre_headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9"])
print("Before: ", pre_headings)

soup, headings = adjust_headings(soup, title_name)
soup = flatten_headings(soup, headings)
# print(soup)
print("After: ", headings)

# breakpoint


def unwrap_stylistic_elements(fixed_html):
    soup = BeautifulSoup(fixed_html, "html.parser")

    stylistic_tags = [
        "b",
        "strong",
        "i",
        "em",
        "mark",
        "small",
        "del",
        "ins",
        "sub",
        "sup",
    ]

    for tag in stylistic_tags:
        for match in soup.findAll(tag):
            match.unwrap()

    s_tag = soup.find("s")
    if s_tag:
        s_tag.decompose()

    return str(soup)


print(soup)


def infer_type(cell_content):
    if re.match(r"^\s*\d+(\.\d+)?\s*$", cell_content):
        return "numeric"
    elif re.match(r"^\s*\d+\.\d+\s*$", cell_content):
        return "numeric"
    return "text"


def wrap_in_tr(soup):
    for table in soup.find_all("table"):
        th_and_td_tags = table.find_all(lambda tag, table=table: tag.name in ["th", "td"] and tag.parent == table)
        if th_and_td_tags:
            tr = soup.new_tag("tr")
            for tag in th_and_td_tags:
                tr.append(tag.extract())
            table.insert(0, tr)
    return str(soup)

def remove_empty_rows(soup):
    all_tables = soup.find_all("table")

    for table in all_tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if all(not cell.get_text(strip=True) for cell in cells):
                row.decompose()

    return str(soup)


def remove_empty_columns(soup):
    all_tables = soup.find_all("table")

    for table in all_tables:
        rows = table.find_all("tr")
        num_cols = len(rows[0].find_all(["td", "th"])) if rows else 0

        for col_idx in range(num_cols):
            cells = [
                row.find_all(["td", "th"])[col_idx]
                for row in rows
                if row.find_all(["td", "th"])
            ]
            if all(not cell.get_text(strip=True) for cell in cells):
                for cell in cells:
                    cell.decompose()

    return str(soup)


def split_table_by_th(fixed_html):
    soup = BeautifulSoup(fixed_html, "html.parser")
    all_tables = soup.find_all("table")
    tables_html = []

    for table in all_tables:
        current_section = None
        section_soup = BeautifulSoup("", "html.parser")
        first_row = True

        for row in table.find_all("tr"):
            header = row.find("th")
            if header and not first_row:
                if current_section:
                    tables_html.append(str(section_soup))
                    section_soup = BeautifulSoup("", "html.parser")
                current_section = section_soup.new_tag("table")
                section_soup.append(current_section)
            elif not current_section:
                current_section = section_soup.new_tag("table")
                section_soup.append(current_section)
            current_section.append(row)
            first_row = False

        if current_section:
            tables_html.append(str(section_soup))

    return tables_html


def extract_innermost_tables(table):
    inner_tables = table.find_all("table")
    if not inner_tables:
        return [str(table)]  # Return the HTML of the table as a string

    else:
        result = []
        for inner in inner_tables:
            if inner.find("table"):  # If the inner table contains other tables
                continue  # Skip it
            data = extract_innermost_tables(inner)
            result.extend(data)
        return result


def convert_td_to_th_in_first_row(soup):
    all_tables = soup.find_all("table")

    for table in all_tables:
        first_row = table.find("tr")
        if first_row:
            for td in first_row.find_all("td"):
                td.name = "th"

    return soup


def is_table(html_content):

    fixed_html = unwrap_stylistic_elements(html_content)

    soup = BeautifulSoup(fixed_html, "html.parser")
    table = soup.find("table")
    output = ""
    # Check if input is a table
    if not table:
        print("Input is not a table")
        return False

    output = ""

    # Check if there are rows
    if not table.find_all("tr"):
        print("Table has no rows")
        return False

    # If there are rows, check if there are columns
    if not table.find_all(["td", "th"]):
        print("Table has no columns")
        return False

    # Find direct 'th' elements and rows
    direct_th_td = table.find_all(["th", "td"], recursive=False)

    if direct_th_td:
        print(
            "Warning: Direct 'th' or 'td' elements found, attempting to fix irregular structure"
        )
        fixed_html = wrap_in_tr(soup)
        soup = BeautifulSoup(fixed_html, "html.parser")
        fixed_html = str(soup)
        print(fixed_html)

    # Check number of columns
    rows = table.find_all("tr")

    th_td_positions = []
    all_cells = table.find_all(["th", "td"])

    for index, cell in enumerate(all_cells):
        if cell.name == "th":
            th_td_positions.append(index)

    if th_td_positions and (
        th_td_positions[0] != 0
        or any(
            x != th_td_positions[i - 1] + 1
            for i, x in enumerate(th_td_positions)
            if i > 0
        )
    ):
        print(
            "Warning: Seems like nested tables are present, attempting to fix irregular structure\n"
        )
        # print(fixed_html)
        sections = split_table_by_th(fixed_html)
        results = []
        for section in sections:
            result = is_table(section)  # Recursive call for each section
            result = wrap_in_tr(BeautifulSoup(section, "html.parser"))
            results.append(result)
        return results

    # Zipping columns
    columns = zip(*[row.find_all(["td", "th"]) for row in rows])

    # Get the number of columns for each row
    num_cols_per_row = [len(row.find_all(["td", "th"])) for row in rows]

    # Check if all rows have the same number of columns
    if len(set(num_cols_per_row)) > 1:
        print("Rows have different numbers of columns. Probably not a table.")

    # If all rows have the same number of columns, get that number
    num_cols = num_cols_per_row[0]

    print(f"Number of columns: {num_cols}, Number of rows: {len(rows)}")

    if num_cols == 1 and len(rows) > 1:
        print("Probably a list (based on number of columns")

    if len(rows) == 1 and num_cols > 1:
        print("Probably a list (based on number of rows")
        row_of_data = pd.read_html(StringIO(fixed_html))[0]
        # transpose table
        column_of_data = row_of_data.T
        fixed_html = column_of_data.to_html(index=False, header=True)

    if len(rows) * num_cols == 2:
        print("Probably single key-value pair (based on number of rows and columns")

        return fixed_html

    first_child = table.find(["th", "tr"], recursive=False)

    # Check if the first child is a 'th' outside a 'tr' and has a 'td' sibling
    first_row_has_single_th_td = False
    if first_child.name == "th":
        next_sibling_td = first_child.find_next_sibling("td", recursive=False)
        if next_sibling_td:
            first_row_has_single_th_td = True

    # Check each row for a single 'th' and 'td'
    list_like_structure = all(
        len(row.find_all("th")) == 1 and len(row.find_all("td")) == 1 for row in rows
    )

    if first_row_has_single_th_td and list_like_structure:
        print(
            "Probably a list (each row including first has exactly one 'th' and one 'td')"
        )
        sections = split_table_by_th(fixed_html)
        results = []
        for section in sections:
            result = is_table(section)  # Recursive call for each section
            results.append(result)
        return results

    # for i, column in enumerate(columns):
    #     column_types = [infer_type(cell.get_text(strip=True))
    #                     for cell in column if cell.get_text(strip=True)]
    #     most_common_type = max(set(column_types), key=column_types.count)
    #     if column_types and column_types[0] != most_common_type:
    #         print(
    #             f"First cell in column {i+1} is of a different type, likely a header")
    #     else:
    #         print(
    #             f"Probably a table (based on consistent column data types after the first cell\nColumn data types: {column_types}, column: {column}")

    # Check for headers
    if table.find("th"):
        # check if headers are empty
        if not table.find("th").get_text(strip=True):
            print("Probably a list (based on presence of empty headers)")
        # append headers
        else:
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            # get headers using beautiful soup
            header_soup = BeautifulSoup(str(table.find("th")), "html.parser")
            # dissolve all tags
            header_text = header_soup.get_text(strip=True)
            print(
                f"Might be list or table (based on presence of headers), Headers: {header_text}"
            )

    # # Check for nested tables
    # if table.find('table'):
    #     print("Probably a list (based on presence of nested tables)")

    # # Check uniformity of rows
    # if len(set(len(row.find_all(['td', 'th'])) for row in rows)) > 1:
    #     print("Probably a list (based on non-uniformity of rows)")

    # Check for rows and columns in the table
    rows = table.find_all("tr")

    if rows:
        num_columns = max(len(row.find_all(["td", "th"])) for row in rows)
    else:
        num_columns = 0

    print(f"Found {num_columns} columns")

    # Check if the count of direct 'th' matches the number of columns
    if len(direct_th_td) == num_columns:
        print(soup.prettify())
        print("----------Warning: Headers detected outside of standard 'tr' structure")
        fixed_html = wrap_in_tr(soup)

    # check if any rows or columns are all empty
    if any(not row.find_all(["td", "th"]) for row in rows):
        print("Removing empty rows")

        fixed_html = remove_empty_rows(soup)
        # soup = BeautifulSoup(fixed_html, 'html.parser')
        # fixed_html = str(soup)

        sections = split_table_by_th(fixed_html)
        results = []
        for section in sections:
            result = is_table(section)  # Recursive call for each section
            results.append(result)
        return results
    # if they're empty or contain just whitespace
    if any(not column for column in columns) or any(column == [" "] for column in columns):
        print("Removing empty columns")

        sections = split_table_by_th(fixed_html)
        results = []
        for section in sections:
            result = is_table(section)  # Recursive call for each section
            results.append(result)
        # return results

        fixed_html = remove_empty_columns(soup)
        soup = BeautifulSoup(fixed_html, "html.parser")
        fixed_html = str(soup)


    # Check if it's a multiple list
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if "td" in [cell.name for cell in cells]:
            first_td_index = next(
                i for i, cell in enumerate(cells) if cell.name == "td"
            )
            if "th" in [cell.name for cell in cells[first_td_index:]]:
                print("Warning: 'th' found after 'td' in a row")

    # If none of the above checks were conclusive, default to table
    print("Defaulting to table-like structure")

    soup = convert_td_to_th_in_first_row(soup)

    return fixed_html

wikihtml = str(soup)

# check all tables
wikihtml = re.sub(r"\n", " ", wikihtml)  # Replace newlines with spaces

# print(wikitext)

soup = BeautifulSoup(wikihtml, "html.parser")

print(title_name)

print(soup.prettify())


if soup.find("table") is None:
    print("No tables found")
    tables = []



else:
    print("Tables found")
    tables = extract_innermost_tables(soup)

    # print(tables)
for table in tables:
    # print(table)
    soup = BeautifulSoup(table, "html.parser")
    returned_table = is_table(table)
    if isinstance(returned_table, list):
        print("---Table was chunked-----")
        for split_table in returned_table:
            # print(split_table)
            df_list = pd.read_html(StringIO(split_table))
            for df in df_list:
                print(df.to_json(orient="records"))
                print(df)
                print("--------")
    else:
        print("--------")
        df_list = pd.read_html(StringIO(returned_table))
        for df in df_list:
            records = df.to_json(orient="records")
            print(df)
        print("--------")
