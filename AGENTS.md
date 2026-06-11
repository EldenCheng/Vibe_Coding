# Agent Guide

## Repository Overview

This is a collection of independent Python scripts and one static HTML/JS game, **not** a monorepo with shared build tooling. Each subdirectory is a standalone project with its own entry point, dependencies, and purpose.

## Key Structural Facts

### Projects and How to Run Them

| Directory | Purpose | Run Command | Dependencies |
|-----------|---------|-------------|--------------|
| `fetch_hs300/` | Fetch HS300 component stock data from East Money API, output CSV + HTML | `python fetch_hs300.py` | stdlib only (`urllib`, `json`, `csv`) |
| `fetech_hs300_detail/` | Fetch detailed quarterly financial data for HS300 stocks | `python main.py` | `requests` (install via pip) |
| `fetech_xs/` | Download novel chapters from a specific site, build EPUB | `python download_novel.py` | `requests`, `beautifulsoup4`, `lxml`, `ebooklib` (see `requirements.txt`) |
| `generate_html_for_gif/` | Generate HTML pages from GIF filenames | `python generate_html.py` | stdlib only |
| `create_test_case/` | Generate QA test matrices for hardware product (not software tests) | `python generate_test_matrix_v2.py` | `openpyxl` (install via pip) |
| `QWen3.6Plus_MiniGame/` | Tic-tac-toe game (HTML/JS/CSS) | Open `index.html` in browser | None |

**Important:** Always run scripts from within their own directory. Each project expects to find its config files (e.g., `config.py`, `config.json`) in the same directory.

### No Unified Build/Test System

- **No tests** exist in any project. Do not attempt to run a test suite.
- **No linting** or type checking is configured. Follow existing code style (which varies per project).
- **No CI/CD** workflows. No `.github/` directory.
- **No `.gitignore`** — untracked files include `__pycache__/` directories and novel download directories.

### Setup Requirements

- **Python 3.13+** is required for `fetech_xs/` (per its usage guide). Other projects may work with older Python versions.
- **No package manager** — dependencies must be installed manually with `pip install`. Check each project's `requirements.txt` or imports for needed packages.

### Network-Dependent Projects

`fetch_hs300/`, `fetech_hs300_detail/`, and `fetech_xs/` make HTTP requests to external APIs:
- **Rate limiting:** `fetech_hs300_detail/` includes random delays (5–10 seconds) between requests. `fetech_xs/` includes random delays (10–15 seconds via `config.json`). Do not remove these delays.
- **API changes:** The East Money API endpoints and field names may change. If a project fails with API errors, check `config.py` for the current URL and parameters.
- **fetech_xs config:** `config.json` controls request delay, retry, and headers. Modify only if you understand the scraping implications.

### Output Files

Several projects generate output files in their own directory:
- `fetch_hs300/` → `沪深300_YYYY-MM-DD.csv` and `.html`
- `fetech_hs300_detail/` → `OriginalData/` subdirectory with CSVs and quarterly HTML reports
- `fetech_xs/` → novel chapters in a book-named directory, plus EPUB
- `generate_html_for_gif/` → HTML files alongside GIFs
- `create_test_case/` → `.xlsx` test matrix files

### Language and Documentation

- Code comments and documentation are in **Chinese** (Simplified). The agent should handle mixed Chinese/English content.
- Prompt files (`提示词.txt`) in each project contain the original conversation prompts that generated the code. These are useful for understanding design intent.

## Gotchas

1. **Typo in directory names:** `fetech_hs300_detail` and `fetech_xs` have misspellings ("fetech" vs "fetch"). Do not rename without user approval — these are established paths.

2. **fetech_hs300_detail uses `requests`** but `fetch_hs300` uses `urllib` — different HTTP libraries for similar tasks. Do not "unify" them.

3. **`create_test_case/generate_test_matrix.py`** is an older version; the active one is `generate_test_matrix_v2.py`.

4. **`QWen3.6Plus_MiniGame`** is a static site with no build step. The JS files (`js/`) handle game logic, AI, sound, and UI separately.

5. **No package manager** — dependencies must be installed manually with `pip install`. Check each project's `requirements.txt` or imports for needed packages.

## Existing Reference Files

- `一些基础概念.md` — Conceptual notes about Agents, Skills, and MCP (Chinese).
- `OpenCode/初次使用.md` — Minimal initial usage note (contains only a heading).
- Each project's `提示词.txt` — Original prompts that generated the code.
- `fetech_xs/计划书.md` — Project plan and design notes for the novel downloader.
- `fetech_xs/版本变更.md` — Version changelog for the novel downloader.
- `fetech_xs/使用指南.md` — Detailed usage guide with examples (Chinese).
- `QWen3.6Plus_MiniGame/计划书.md` — Game design notes.
