#docker stop app
#docker rm app
#docker build --tag analyzer .

shopt -ou noglob
shopt -u failglob
shopt -s nullglob

for file in resources/replays/aiarena/*.SC2Replay; do
  file_name=$(basename -- "$file")
  replay_glob="root/replays/$file_name"
  docker run -dit \
    --mount type=bind,src="$(pwd)/resources/replays/aiarena",dst="/root/replays" \
    --env REPLAY_GLOB="$replay_glob" \
    analyzer
done