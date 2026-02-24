# Hello, Friend

- Let's do magic together
- Be intuitive, imaginative and free.
- Be pragmatic, critical and objective.
- Be explicit about what you know and what you don't know.

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

The central bot file is phantom/agent.py, always read it before modifying the codebase.

# Codex Instructions

codex directory is our dialogue.
When working on a specific idea with a corresponing .md file, use it for record keeping.
Don't create you own .md files unless instructed.
Store knowledge you gained along the way into knowledge.md.
everything that might save you and others a bunch of time in the future is worth remembering.
Focus on Understanding about the project, ares, python-sc2 and Starcraft II strategy.

# Coding Style

* short and readable, especially for high level classes
* when boilerplate is necessary, offload into seperate folders
* offload generic utilities into common/ subfolders
* directories with subdirectories should contain minimal number of files (within reason)
* leave __init__ files empty per default
* prefer adding new files over editing existing ones
* ask before making bigger functional changes to existing code.

# Testing

Use `make check` and `make fix` to validate the code.
No dummy bots. Test only bot-independent components.

# Notes

- prefer plotly over matplotlib for complex graphs
- prefer click commands over argpase, add config file support at 3+ params
- use dark skin for plots