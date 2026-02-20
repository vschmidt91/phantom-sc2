# Structure

- build: ignore
- codex: your home
- models: ML models, unused
- notebooks: EDA and benchmarks, ignore
- config: all the ways to run the bot
- phantom: source root
- resources: junk pile
- scripts: executables 
- run.py: bot entry point
- tests: ignore

# Codex Persistent Home

codex directory is our dialogue.
Store knowledge int codex/knowledge.md.
everything that might save you and others a bunch of time in the future is worth remembering.
Focus on Understanding about the project, ares, python-sc2 and Starcraft II strategy.

# Coding Style

* short and readable, especially for high level classes
* offload boilerplate into seperate folders when absolutely necessary
* offload generic utilities into common/ subfolders
* directories with subdirectories should contain minimal number of files (within reason)

# Testing

Only run `make fix check` before comitting changes and fix what comes up.
Do the python compilation check, otherwise ignore testing completely.