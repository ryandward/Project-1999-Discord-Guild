import requests
import json
import mwparserfromhell

def fetch_wikitext(page):
    """ Fetch the raw wikitext of a page """
    url = "https://wiki.project1999.com/api.php"
    params = {
        "action": "query",
        "format": "json",
        "titles": page,
        "prop": "revisions",
        "rvprop": "content"
    }
    response = requests.get(url, params=params, verify = False)
    data = response.json()
    pageid = list(data['query']['pages'].keys())[0]
    return data['query']['pages'][pageid]['revisions'][0]['*']

def parse_wikitext(wikitext):
    """ Parse wikitext and extract table data and section headers """
    wikitext = wikitext.replace("'''", "").replace("''", "")

    parsed = mwparserfromhell.utils.parse_anything(wikitext, skip_style_tags=True)

    data = {}
    current_section = None
    current_subsection = None

    section_path = []
    for node in parsed.nodes:
        if isinstance(node, mwparserfromhell.nodes.Heading):
            title = str(node.title).strip()
            while len(section_path) >= node.level:
                section_path.pop()
            section_path.append(title)
            current_section = data
            for section in section_path:
                current_section = current_section.setdefault(section, {})
        elif isinstance(node, mwparserfromhell.nodes.Tag) and node.tag == 'table':
            rows = []
            for template in node.contents.filter_templates():
                row_data = {}
                for param in template.params:
                    param_name = str(param.name).strip()
                    if isinstance(param.value, mwparserfromhell.wikicode.Wikicode):
                        wikicode = param.value
                        if wikicode.filter_templates():
                            template = wikicode.filter_templates()[0]
                            row_data[param_name] = str(template.name).strip()
                        elif wikicode.filter_wikilinks():
                            wikilink = wikicode.filter_wikilinks()[0]
                            row_data[param_name] = str(wikilink.title).strip()
                        else:
                            row_data[param_name] = str(wikicode).strip()
                    else:
                        row_data[param_name] = str(param.value).strip()
                if row_data:
                        rows.append(row_data)
            if rows:
                current_section = data
                for section in section_path:
                    current_section = current_section.setdefault(section, {})
                for row in rows:
                    if 'name' in row:
                        current_section[row['name']] = row

        # elif isinstance(node, (mwparserfromhell.nodes.Text, mwparserfromhell.nodes.Wikilink)):
        #     current_section = data
        #     for section in section_path:
        #         current_section = current_section.setdefault(section, {})
        #     current_section += " " + str(node.title if isinstance(node, mwparserfromhell.nodes.Wikilink) else node)
            
            # if not rows:
            #     table_text = str(node.contents)
            #     for row_text in table_text.split('|-'):
            #         row_data = [cell.strip() for cell in row_text.split('||')]
            #         if any(row_data):  # Check if row_data is not empty
            #             rows.append(row_data)

    return data

# Example usage
classes = ["Bard", "Enchanter", "Magician", "Necromancer", "Wizard", "Cleric", "Druid", "Shaman", "Monk", "Ranger", "Rogue", "Paladin", "Shadow Knight", "Warrior"]

for page in classes:
    wikitext = fetch_wikitext(page)
    tables = parse_wikitext(wikitext)

    json_data = json.dumps(tables, indent=4)
    
    with open(f'Lore/{page}.json', 'w') as f:
        f.write(json_data)

# page = "Warrior"
# wikitext = fetch_wikitext(page)
# tables = parse_wikitext(wikitext)

# json_data = json.dumps(tables, indent=4)
# print(json_data)
