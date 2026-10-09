# Agent Guide

## Repository Overview



### No Unified Build/Test System

- **No tests** exist in any project. Do not attempt to run a test suite.
- **No linting** or type checking is configured. Follow existing code style (which varies per project).
- **No CI/CD** workflows. No `.github/` directory.
- **No `.gitignore`** — untracked files include `__pycache__/` directories and novel download directories.

### Setup Requirements

- **Python 3.13+** is required for `fetech_xs/` (per its usage guide). Other projects may work with older Python versions.
- **No package manager** — dependencies must be installed manually with `pip install`. Check each project's `requirements.txt` or imports for needed packages.

### Network-Dependent Projects



### Output Files



## Existing Reference Files



## Requirements

- 在编写代码之前, 先将设计好软件结构, 编码过程等等的项目资料, 并将这些资料统一存放在一个项目设计文档.md的文件里, 并且如果设计有变更, 也要根据变更的内容先更新这份文档

- 每一个项目都维护一个版本变更.md文件, 记录版本间的变化

- 不要主动为我决定任何事, 如果有不确定的东西, 问问我的意见

- 我也不是全能的, 如果我的要求中有不常理的; 或者我提出的实现方法中, 你有更好的实现办法, 提出来问问我, 让我再决定

- 编写python时合理拆分模块, 实现关键功能的地方加上中文注释

## Others

- 本机python运行命令是"py"
