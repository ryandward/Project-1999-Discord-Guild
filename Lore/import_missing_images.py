import requests

# Start a session
session = requests.Session()

# Step 1: Get login token
response = session.get("http://localhost/mediawiki/api.php?action=query&meta=tokens&type=login&format=json")
login_token = response.json()['query']['tokens']['logintoken']

# Step 2: Log in
login_data = {
    'action': "login",
    'lgname': "renobot",
    'lgpassword': "sakura1010",
    'lgtoken': login_token,
    'format': "json"
}
response = session.post("http://localhost/mediawiki/api.php", data=login_data)

print(response.json())



# Step 3: Get the wanted files
wanted_files_params = {
    'action': "query",
    'list': "querypage",
    'qppage': "Wantedfiles",
    'qplimit': 5000,  # Increase the limit

    'format': "json"
}
response = session.get("http://localhost/mediawiki/api.php", params=wanted_files_params)

# Print the titles of the wanted files
wanted_files = response.json()['query']['querypage']['results']
for file in wanted_files:
    # change the name of the file to remove spaces and replace them with underscores
    print(file['title'])

import warnings
import requests
import mwclient
import urllib3

# Suppress only the specific Unverified HTTPS request warning
warnings.filterwarnings('ignore', 'Unverified HTTPS request is being made.*',
                        urllib3.exceptions.InsecureRequestWarning)

# Local MediaWiki configuration
LOCAL_WIKI_SITE = "localhost"
LOCAL_WIKI_PATH = "/mediawiki/"  # replace with your local wiki's path
LOCAL_WIKI_USERNAME = "renobot"  # replace with your local wiki's username
LOCAL_WIKI_PASSWORD = "sakura1010"  # replace with your local wiki's password


# Remote MediaWiki configuration
REMOTE_WIKI_SITE = "wiki.project1999.com"
REMOTE_WIKI_API_PATH = "/api.php"

# Initialize session for requests
session = requests.Session()

# Function to get MediaWiki API tokens
def get_token(site, token_type):
    response = session.get(f"http://{site}/mediawiki/api.php", params={'action': 'query', 'meta': 'tokens', 'type': token_type, 'format': 'json'})
    return response.json()['query']['tokens'][f'{token_type}token']

# Login to local MediaWiki
def login_to_mediawiki(site, username, password):
    login_token = get_token(site, 'login')
    login_data = {
        'action': "login",
        'lgname': username,
        'lgpassword': password,
        'lgtoken': login_token,
        'format': "json"
    }
    return session.post(f"http://{site}/mediawiki/api.php", data=login_data)

# Login to local wiki
response = login_to_mediawiki(LOCAL_WIKI_SITE, LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)
print("Login to local wiki:", response.json())

# Connect to local and remote sites using mwclient
local_site = mwclient.Site(host=LOCAL_WIKI_SITE, path=LOCAL_WIKI_PATH, scheme='http')
local_site.login(LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)
remote_site = mwclient.Site(host=REMOTE_WIKI_SITE, reqs={"verify": False}, path="/")

def transfer_file(file_name):
    try:
        # Retrieve file URL from remote wiki using imageinfo API
        response = session.get(f"https://{REMOTE_WIKI_SITE}/api.php", params={
            'action': 'query',
            'titles': file_name,
            'prop': 'imageinfo',
            'iiprop': 'url',
            'format': 'json'
        },
        verify=False)
        response.raise_for_status()

        pages = response.json()['query']['pages']
        image_info = next(iter(pages.values())).get('imageinfo')

        if image_info:
            file_url = image_info[0]['url']
            description = "Transferred from remote site"
        else:
            file_url = f"https://{REMOTE_WIKI_SITE}/{file_name}"
            description = file_name

        # Download the file
        response = session.get(file_url, stream=True)
        response.raise_for_status()

        # Save the file locally
        local_file_path = f"/tmp/{file_name}"
        with open(local_file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Upload the file to the local site
        with open(local_file_path, 'rb') as f:
            local_site.upload(f, filename=file_name, description=description, ignore=True)
        
        print(f"Successfully transferred: {file_name}")

    except Exception as e:
        print(f"Error transferring file {file_name}: {e}")

        #except Invalid CSRF token error
        if "Invalid CSRF token" in str(e):
            # Login to local wiki again
            response = login_to_mediawiki(LOCAL_WIKI_SITE, LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)
            print("Login to local wiki:", response.json())

            # Retry
            transfer_file(file_name)


# List of files to transfer
# wanted_files = ["File:WarningIcon.png", "File:Imbued field plate human female.jpg", "File:Sinfully handsome.png", "File:Zallah.jpg", "File:Spectres.png", "File:Npc lendiniara the keeper.png", "File:Npc vira.png", "File:SectsSyrupFlamer.png", "File:EruditeSteelsilkback.jpg", "File:EruditeSteelsilkfront.jpg"]

# Transfer each file
for file in wanted_files:
    transfer_file(file['title'])
