docker stop app
docker rm app
docker build --tag analyzer .
docker run -it -d \
  --mount type=bind,src="$(pwd)/resources/replays/aiarena",dst="/root/Documents/StarCraft II/Replays" \
  --name app analyzer
docker exec -i app bash -c "poetry run python scripts/analyze_replays.py '/root/Documents/StarCraft II/Replays'"