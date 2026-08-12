# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

BlueScore is a new, largely unimplemented Python project. At present:

- `app.py`, `requirements.txt`, and `.env.example` exist but are empty.
- `chain/`, `data/`, `explain/`, and `score/` are placeholder directories (each contains only a `.gitkeep`), suggesting an intended module layout — likely a chain/pipeline component, data handling, an explanation/interpretability component, and a scoring component — but none of these have been implemented yet.
- There is no build, lint, or test tooling configured yet (no `pytest.ini`, `pyproject.toml`, `setup.py`, CI config, etc.).

Since there is no existing code or established conventions, use judgment based on the directory names above when deciding where new code belongs, and set up standard Python tooling (dependency management, tests, linting) as the project grows rather than assuming a pattern that isn't there yet.

When substantial code is added to this repo, this file should be updated with real build/lint/test commands and an accurate architecture overview.

## File ownership convention

Ownership by folder/area is tracked in `ROLES.md`. When creating a new file, check `ROLES.md` for the owner(s) of that folder/area and add a `담당: {이름}` line near the top of the file (as a comment in the file's comment syntax, e.g. inside the module docstring for `.py` files or as a heading line for `.md` files). Keep `ROLES.md` and this convention in sync if ownership changes.
