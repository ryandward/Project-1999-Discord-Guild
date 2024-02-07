import mwclient
import mwparserfromhell


# Local MediaWiki configuration
LOCAL_WIKI_SITE = "localhost"
LOCAL_WIKI_PATH = "/mediawiki/"  # replace with your local wiki's path
LOCAL_WIKI_USERNAME = "renobot"  # replace with your local wiki's username
LOCAL_WIKI_PASSWORD = "sakura1010"  # replace with your local wiki's password

# Connect to the wiki
site = mwclient.Site(host=LOCAL_WIKI_SITE, path=LOCAL_WIKI_PATH, scheme='http')
# Login to the wiki
site.login(LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)

# Iterate over all pages in your wiki
for page in site.allpages():
    # Parse the page text
    old_text = page.text()

    wikicode = mwparserfromhell.parse(page.text())


    # Parse the page text
    wikicode = mwparserfromhell.parse(page.text())

    # Iterate over all templates in the page text
    for template in wikicode.filter_templates():
        # If the template name starts with ':'
        if str(template.name).strip().startswith(':'):
            old_name = str(template.name).strip()[1:]

            # Change the template name to 'ItemLink'
            template.name = 'ItemLink'
            # Take the old name, strip off the ":" and make it a parameter
            template.add(1, old_name)
   # Get the new page text
    new_text = str(wikicode)

    # Print the modified page text
    # print(str(wikicode))
    # Save the modified page text
    if old_text != new_text:
        page.save(str(wikicode), summary='Converted {{:Page}} to {{ItemLink|Page}}')
        print(f"Converted {page.name}")
    else:
        print(f"No changes made to {page.name}")