import click
from requests import HTTPError, Session
from requests.adapters import HTTPAdapter, Retry


@click.command()
@click.argument("bot-zip", type=click.File("rb"))
@click.option("--wiki", type=click.File("rb"))
@click.option("--api-token", envvar="UPLOAD_API_TOKEN")
@click.option("--bot-id", envvar="UPLOAD_BOT_ID")
@click.option("--bot-zip-publicly-downloadable", type=bool, flag_value=True)
@click.option("--bot-data-publicly-downloadable", type=bool, flag_value=True)
@click.option("--bot-data-enabled", type=bool, flag_value=True)
def main(
    bot_zip,
    wiki,
    api_token: str,
    bot_id: str,
    bot_zip_publicly_downloadable: bool,
    bot_data_publicly_downloadable: bool,
    bot_data_enabled: bool,
):
    url = f"https://aiarena.net/api/bots/{bot_id}/"
    print(f"Uploading to {url=}")

    # configure retries in case AIArena does not respond
    session = Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount("https://aiarena.net", HTTPAdapter(max_retries=retries))
    request_headers = {
        "Authorization": f"Token {api_token}",
    }

    request_data = {
        "bot_zip_publicly_downloadable": bot_zip_publicly_downloadable,
        "bot_data_publicly_downloadable": bot_data_publicly_downloadable,
        "bot_data_enabled": bot_data_enabled,
    }
    if wiki:
        request_data["wiki_article_content"] = wiki.read()

    request_files = {
        "bot_zip": bot_zip,
    }

    response = session.patch(url, headers=request_headers, data=request_data, files=request_files)

    print(f"{response=}")
    print(f"{response.content=}")

    try:
        response.raise_for_status()
    except HTTPError as error:
        print(f"{error=}")
        raise error


if __name__ == "__main__":
    main()
