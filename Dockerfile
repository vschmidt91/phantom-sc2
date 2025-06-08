FROM python:3.12-slim

USER root
WORKDIR /root/

RUN dpkg --add-architecture i386

# Update system
RUN apt-get update && apt-get upgrade --assume-yes --quiet=2
RUN apt-get install --assume-yes --no-install-recommends --no-show-upgraded \
    wget \
    unzip

# Download and uncompress StarCraftII from https://github.com/Blizzard/s2client-proto#linux-packages and remove zip file
#RUN wget -q 'http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.9.2.zip' \
#	&& unzip -P iagreetotheeula SC2.4.9.2.zip \
#	&& rm SC2.4.9.2.zip \
#    && mv SC2.4.9.2/StarCraftII . \
#	&& rm -rf SC2.4.9.2
# RUN chmod +x /root/StarCraftII/Versions/Base74741/SC2_x64

RUN wget -q 'http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip' \
	&& unzip -P iagreetotheeula SC2.4.10.zip \
	&& rm SC2.4.10.zip

# Install common software via APT
RUN apt-get install --assume-yes --no-install-recommends --no-show-upgraded \
    git  \
    make \
    gcc \
    tree \
    gpg \
    procps \
    lsof \
    apt-transport-https \
    libgtk2.0-dev \
    software-properties-common \
    dirmngr \
    gpg-agent \
    g++

# Update APT cache
RUN apt-get update

# Upgrade pip and install pip-install requirements
RUN python3 -m pip install --upgrade pip pipenv

ENV POETRY_CACHE_DIR=/opt/.cache
RUN python3 -m pip install poetry

# Create a symlink for the maps directory
RUN ln -s /root/StarCraftII/Maps /root/StarCraftII/maps

ADD ./build /root/phantom

WORKDIR /root/phantom
RUN poetry install --all-extras

ADD ./resources/maps /root/StarCraftII/maps

ENTRYPOINT ["poetry", "run", "python"]