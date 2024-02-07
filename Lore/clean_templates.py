import sqlite3
import mwparserfromhell

def clean_page_content(page_content):
    wikicode = mwparserfromhell.parse(page_content)

    # Remove <noinclude> sections
    for tag in wikicode.filter_tags(matches=lambda node: node.tag == 'noinclude'):
        wikicode.remove(tag)

    # Replace <includeonly> sections with their content
    for tag in wikicode.filter_tags(matches=lambda node: node.tag == 'includeonly'):
        wikicode.replace(tag, tag.contents)

    # Convert to string
    cleaned_content = str(wikicode)

    # Remove leading and trailing whitespace and empty lines
    cleaned_content = "\n".join([line.strip() for line in cleaned_content.splitlines() if line.strip()])

    return cleaned_content

# Connect to the SQLite database
conn = sqlite3.connect('metadata.db')

# Create a cursor
cur = conn.cursor()

# Create the templates table
cur.execute("""
CREATE TABLE IF NOT EXISTS templates (
    name TEXT PRIMARY KEY,
    content TEXT
)
""")

# Select all pages
cur.execute("SELECT title, content FROM metadata WHERE title LIKE 'Template:%'")

# Fetch all rows
rows = cur.fetchall()

# Iterate over each row
for row in rows:
    # Clean the page content
    cleaned_content = clean_page_content(row[1])
    template_name = row[0].replace('Template:', '')

    # Insert the cleaned content into the templates table
    cur.execute("INSERT OR REPLACE INTO templates (name, content) VALUES (?, ?)", (template_name, cleaned_content))

# Commit the changes
conn.commit()

# Handle redirects
cur.execute("SELECT name, content FROM templates WHERE content LIKE '#REDIRECT%'")
rows = cur.fetchall()

for row in rows:
    # Extract the target template name
    target_template_name = row[1].split('[[', 1)[1].split(']]', 1)[0].replace('Template:', '')

    # Get the content of the target template
    cur.execute("SELECT content FROM templates WHERE name = ?", (target_template_name,))
    target_template_content = cur.fetchone()

    if target_template_content is not None:
        # Replace the redirect with the target template content
        cur.execute("UPDATE templates SET content = ? WHERE name = ?", (target_template_content[0], row[0]))

# Commit the changes
conn.commit()

# Close the connection
conn.close()