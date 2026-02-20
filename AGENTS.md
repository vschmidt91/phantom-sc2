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

# Codex Persistent Home

codex directory is our dialogue.
Store task-specific knowledge into the idea file you are working on.
Keep user input and your report separate in idea. modify user input as part of revisions, but ask.
Store general knowledge into codex/knowledge.md.
everything that might save you and others a bunch of time in the future is worth remembering.
Focus on Understanding about the project, ares, python-sc2 and Starcraft II strategy.

# Coding Style

* short and readable, especially for high level classes
* offload boilerplate into seperate folders when absolutely necessary
* offload generic utilities into common/ subfolders
* directories with subdirectories should contain minimal number of files (within reason)
* leave __init__ files empty per default

# Testing

Use `make check` and `make fix` to validate the code.
No dummy bots. Test only bot-independent components.