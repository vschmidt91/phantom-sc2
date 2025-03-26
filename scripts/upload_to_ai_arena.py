import os

import requests
from requests.adapters import HTTPAdapter, Retry

API_TOKEN_ENV = "UPLOAD_API_TOKEN"
BOT_ID_ENV = "UPLOAD_BOT_ID"
ZIPFILE_NAME = "bot.zip"
WIKI_FILE_NAME = "WIKI.md"
BASE_URL = "https://aiarena.net"

token = os.environ[API_TOKEN_ENV]
bot_id = os.environ[BOT_ID_ENV]
url = f"{BASE_URL}/api/bots/{bot_id}/"
RETRIES = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])

print("Uploading bot")
with (
    open(ZIPFILE_NAME, "rb") as bot_zip,
    open(WIKI_FILE_NAME, "r") as wiki,
):
    request_headers = {
        "Authorization": f"Token {token}",
    }
    request_data = {
        # "bot_zip_publicly_downloadable": False,
        # "bot_data_publicly_downloadable": False,
        # "bot_data_enabled": True,
        "wiki_article_content": wiki.read(),
    }
    request_files = {
        "bot_zip": bot_zip,
    }

    # configure retries in case AIArena does not respond
    session = requests.Session()
    session.mount(BASE_URL, HTTPAdapter(max_retries=RETRIES))
    response = requests.patch(url, headers=request_headers, data=request_data, files=request_files)

    print(response)
    print(response.content)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        raise err
