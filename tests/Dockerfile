# For live version
FROM burnysc2/python-sc2-docker:latest

# Copy files from the current commit (the python-sc2 folder) to root
ADD out /root/python-sc2-docker
ADD tests /root/python-sc2-docker

# Install the python-sc2 library and its requirements (s2clientprotocol etc.) to python
WORKDIR /root/python-sc2-docker
RUN python -m pip install --upgrade pip
RUN python -m pip install -r requirements.txt

# This will be executed during the container run instead:
# docker run test_image -c "python examples/protoss/cannon_rush.py"

ENTRYPOINT [ "/bin/bash" ]
