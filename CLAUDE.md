# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

BlueScore is a new, largely unimplemented Python project. At present:

- `app.py`, `requirements.txt`, and `.env.example` exist but are empty.
- `chain/`, `data/`, `explain/`, and `score/` are placeholder directories (each contains only a `.gitkeep`), suggesting an intended module layout — likely a chain/pipeline component, data handling, an explanation/interpretability component, and a scoring component — but none of these have been implemented yet.
- There is no build, lint, or test tooling configured yet (no `pytest.ini`, `pyproject.toml`, `setup.py`, CI config, etc.).

Since there is no existing code or established conventions, use judgment based on the directory names above when deciding where new code belongs, and set up standard Python tooling (dependency management, tests, linting) as the project grows rather than assuming a pattern that isn't there yet.

When substantial code is added to this repo, this file should be updated with real build/lint/test commands and an accurate architecture overview.
