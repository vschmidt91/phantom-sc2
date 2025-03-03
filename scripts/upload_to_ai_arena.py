import os

import requests

API_TOKEN_ENV: str = "UPLOAD_API_TOKEN"
BOT_ID_ENV: str = "UPLOAD_BOT_ID"
ZIPFILE_NAME: str = "bot.zip"
WIKI_FILE_NAME: str = "WIKI.md"

token = os.environ.get(API_TOKEN_ENV)
bot_id = os.environ.get(BOT_ID_ENV)
url = f"https://aiarena.net/api/bots/{bot_id}/"

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
    response = requests.patch(url, headers=request_headers, data=request_data, files=request_files)

    print(response)
    print(response.content)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        raise err
