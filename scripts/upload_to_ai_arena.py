import click
import requests
from loguru import logger
from requests.adapters import HTTPAdapter, Retry


@click.command()
@click.option("--api-token", envvar="UPLOAD_API_TOKEN")
@click.option("--bot-id", envvar="UPLOAD_BOT_ID")
@click.option("--bot-path", default="bot.zip")
@click.option("--wiki-path", default="resources/WIKI.md")
def main(
    api_token: str,
    bot_id: str,
    bot_path: str,
    wiki_path: str,
):
    url = f"https://aiarena.net/api/bots/{bot_id}/"
    logger.info(f"Uploading {bot_path=} to {url=}")

    # configure retries in case AIArena does not respond
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount("https://aiarena.net", HTTPAdapter(max_retries=retries))
    request_headers = {
        "Authorization": f"Token {api_token}",
    }

    with (
        open(bot_path, "rb") as bot_zip,
        open(wiki_path, "r") as wiki,
    ):
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

        logger.info(f"{response=}")
        logger.info(f"{response.content=}")

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            logger.exception(f"{error=}")
            raise error


if __name__ == "__main__":
    main()
