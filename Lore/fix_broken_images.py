import os
import subprocess
from mwclient import Site
import mwclient

# Local MediaWiki configuration
LOCAL_WIKI_SITE = "localhost"
LOCAL_WIKI_PATH = "/mediawiki/"  # replace with your local wiki's path
LOCAL_WIKI_USERNAME = "renobot"  # replace with your local wiki's username
LOCAL_WIKI_PASSWORD = "sakura1010"  # replace with your local wiki's password

# Directory to save the images
IMAGE_DIR = "Broken_Images"
os.makedirs(IMAGE_DIR, exist_ok=True)

# Connect to the local MediaWiki
site = Site(host=LOCAL_WIKI_SITE, path=LOCAL_WIKI_PATH, scheme='http')
site.login(LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)


# Get all images
images = site.allimages()

for image in images:
    # Process only PNG files
    if image.name.lower().endswith('.png'):
        try:
            # Open a file in write-binary mode
            with open(image.name, 'wb') as f:
                # Download the image
                image.download(f)

            # Fix the image
            fixed_image_name = image.name.replace('.png', '-fixed.png')
            subprocess.run(['png-fix-IDAT-windowsize', '-force', image.name])

            # Open the fixed image in read-binary mode
            with open(fixed_image_name, 'rb') as f:
                # Upload the fixed image
                site.upload(f, image.name, ignore=True)

            # Log the name of the image if the fixed image is different
            with open(image.name, 'rb') as original_file, open(fixed_image_name, 'rb') as fixed_file:
                if original_file.read() != fixed_file.read():
                    with open('replaced_images.log', 'a') as log_file:
                        log_file.write(f"{image.name}\n")

        except mwclient.errors.APIError as e:
            if e.code == 'badtoken':
                print("CSRF token expired. Re-logging in...")
                site.login(LOCAL_WIKI_USERNAME, LOCAL_WIKI_PASSWORD)
            elif e.code == 'fileexists-no-change':
                print(f"Skipping {image.name}: The upload is an exact duplicate of the current version.")
            else:
                print(f"Error processing {image.name}: {e}")
        except Exception as e:
            print(f"Error processing {image.name}: {e}")
        finally:
            # Delete the original and fixed image files if they exist
            if os.path.exists(image.name):
                os.remove(image.name)
            if os.path.exists(fixed_image_name):
                os.remove(fixed_image_name)