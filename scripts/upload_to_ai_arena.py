import click
from requests import HTTPError, Session
from requests.adapters import HTTPAdapter, Retry


@click.command()
@click.argument("bot-zip", type=click.File("rb"))
@click.option("--wiki", type=click.File("rb"))
@click.option("--api-token", envvar="UPLOAD_API_TOKEN")
@click.option("--bot-id", envvar="UPLOAD_BOT_ID")
def main(
    bot_zip,
    wiki,
    api_token: str,
    bot_id: str,
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

    request_data = {}
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
