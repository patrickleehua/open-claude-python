<div align="center">

# Open Claude Python

**A production-grade autonomous coding agent, rebuilt in Python.**

Inspired by [Claude Code](https://docs.anthropic.com/en/docs/claude-code), fully open-source.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://docs.astral.sh/ruff/)

</div>

---

## Why This Exists

Claude Code proved that an AI agent can be a real pair programmer — reading your codebase, running commands, editing files, and looping until the job is done. But it's closed-source, Node.js-only, and tightly coupled to Anthropic's platform.

**Open Claude Python** asks: *what would it take to build that same experience, in Python, with public data and open protocols?*

The answer is an architecture centered around a powerful **agentic tool loop** — stream LLM responses, detect tool calls, execute them, feed results back, and repeat — combined with a permission system, memory, MCP protocol support, and a rich TUI.

---

## Demo

<div align="center">
  <video src="https://raw.githubusercontent.com/patrickleehua/open-claude-python/main/images/example.mp4" controls muted playsinline preload="metadata" width="960">
    Your browser does not support embedded videos.
  </video>
  <p>
    <a href="https://raw.githubusercontent.com/patrickleehua/open-claude-python/main/images/example.mp4">Open the demo video directly</a>
  </p>
</div>

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                         Textual TUI                          │
│                   (Rich terminal interface)                   │
├──────────────┬────────────────────────────┬──────────────────┤
│  Slash Cmds  │   Permission Dialogs       │   Design System  │
│  /help /bug  │   allow / deny / ask       │   tokens & theme │
├──────────────┴────────────────────────────┴──────────────────┤
│                       Query Engine                            │
│          stream → parse → tool_use → execute → loop           │
│              (multi-turn agentic core, up to N turns)          │
├──────────┬──────────┬───────────┬──────────┬─────────────────┤
│  Tools   │   MCP    │  Memory   │  Hooks   │   Coordinator   │
│  Read    │  proto   │  session  │  pre/post│   multi-agent   │
│  Write   │  client  │  auto     │  tool    │   orchestration │
│  Edit    │  server  │  extract  │  notif   │                 │
│  Bash    │          │  dream    │          │                 │
│  Grep    │          │           │          │                 │
│  Glob    │          │           │          │                 │
│  Web*    │          │           │          │                 │
├──────────┴──────────┴───────────┴──────────┴─────────────────┤
│                        Services Layer                         │
│   API Client │ OAuth │ Settings │ Compact │ Session Memory     │
│   AutoDream  │ Extract Memories │ Policy Limits │ Analytics   │
├───────────────────────────────────────────────────────────────┤
│                      Anthropic SDK (async)                    │
│              streaming + tool_use + extended thinking          │
└───────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### Agentic Tool Loop

The heart of the system. The `QueryEngine` runs a multi-turn loop:

1. **Stream** an LLM response with tool definitions attached
2. **Parse** content blocks — text, thinking, tool_use
3. **Execute** each tool call (with permission checks)
4. **Feed** tool results back into the conversation
5. **Repeat** until `end_turn` or max turns reached

Each turn yields `StreamEvent` objects so the UI can render in real-time.

### Tool System

Every tool inherits from `Tool` (ABC) and implements:

```python
class MyTool(Tool):
    name = "MyTool"           # model-facing identifier
    input_schema = MyInput    # Pydantic model for validation
    description = "..."       # included in API tool definition

    async def call(self, input_data: MyInput) -> str:
        ...  # execute and return result string
```

Built-in tools: `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`, `WebFetch`, `WebSearch`, `NotebookEdit`, `AgentTool` (sub-agent spawning), `MCPTool` (proxy to MCP servers).

### Permission Pipeline

Before any tool executes, it passes through a multi-stage permission pipeline:

```
Rule Parser → Auto Mode State → Classifier → Interactive Ask → Execute / Deny
```

Rules come from `.claude/settings.json`, support glob patterns, and can be set to `allow`, `deny`, or `ask` per tool and path.

### Memory System

Three layers of persistent memory:

| Layer | Purpose | Trigger |
|---|---|---|
| **Session Memory** | Auto-summarize current conversation | After N messages |
| **Memory Extract** | Extract key facts to markdown files | Background, periodic |
| **AutoDream** | Consolidate memories across sessions | Time-gated (24h) + session threshold |

All memories stored as markdown with frontmatter in `.claude/memory/`.

### MCP Protocol

Full [Model Context Protocol](https://modelcontextprotocol.io/) support — connect to external tool/data servers, authenticate via OAuth, and proxy tool calls transparently.

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| CLI | [Typer](https://typer.tiangolo.com/) | Type-safe CLI with auto-docs |
| TUI | [Textual](https://textual.textualize.io/) | Async terminal UI framework |
| Output | [Rich](https://rich.readthedocs.io/) | Beautiful terminal formatting |
| LLM | [anthropic](https://github.com/anthropics/anthropic-sdk-python) | Official async SDK, streaming + tool_use |
| Schema | [Pydantic v2](https://docs.pydantic.dev/) | Input validation, JSON schema generation |
| MCP | [mcp](https://github.com/modelcontextprotocol/python-sdk) | Model Context Protocol client/server |
| HTTP | [httpx](https://www.python-httpx.org/) | Async HTTP with retries |
| Storage | [keyring](https://github.com/jaraco/keyring) | OS-level secure credential storage |
| I/O | [aiofiles](https://github.com/Tinche/aiofiles) | Async file operations |

---

## Project Structure

```
src/open_claude/
├── query/                    # Core agentic engine
│   ├── engine.py             #   QueryEngine — stream + tool loop
│   ├── streaming.py          #   SSE stream parser
│   ├── message_builder.py    #   Message normalization
│   └── types.py              #   StreamEvent, TokenUsage, QueryResult
├── tools/                    # Tool implementations
│   ├── base.py               #   Tool ABC + registry
│   └── shared/               #   Shared tool utilities
├── components/               # Textual UI components
│   ├── ui/                   #   Chat app, message widgets
│   ├── permissions/          #   Permission dialogs
│   └── design_system/        #   Design tokens & theme
├── services/                 # Core services
│   ├── api/                  #   API client, retry, errors
│   ├── compact/              #   Context compression
│   ├── session_memory/       #   Auto session summarization
│   ├── auto_dream/           #   Cross-session memory consolidation
│   ├── extract_memories/     #   Memory extraction
│   ├── mcp/                  #   MCP server management
│   └── settings/             #   Settings loader
├── commands/                 # Slash commands
├── context/                  # Prompt building, git context, CLAUDE.md
├── coordinator/              # Multi-agent orchestration
├── hooks/                    # Hook system (pre/post tool)
├── schemas/                  # Pydantic data schemas
├── utils/
│   ├── permissions/          #   Permission pipeline
│   ├── memory/               #   Memory file management
│   └── mcp/                  #   MCP utilities
└── constants/                # Prompts, defaults
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install & Run

```bash
# Clone
git clone https://github.com/your-org/open-claude-python.git
cd open-claude-python

# Install dependencies
uv sync

# Set your API key
export ANTHROPIC_API_KEY="sk-..."

# Launch
uv run claude-py
```

### Headless Mode

```python
import asyncio
from anthropic import AsyncAnthropic
from open_claude.query.engine import QueryEngine

async def main():
    client = AsyncAnthropic()
    engine = QueryEngine(client)
    messages = [{"role": "user", "content": "Read pyproject.toml and summarize it"}]

    async for event in engine.query_with_tool_loop(messages, tools=my_tool_defs, tool_executor=executor):
        if event.type == "text":
            print(event.content, end="", flush=True)

asyncio.run(main())
```

---

## Development

```bash
# Install with dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Type check
uv run mypy src/open_claude

# Lint
uv run ruff check src/open_claude

# Format
uv run ruff format src/open_claude
```

---

## Development Progress

~11,000 lines of Python across 153 files. Benchmarked against the original Claude Code (TypeScript) with 53+ tools, 87+ commands, and ~148 component files.

> Detailed progress docs: [`docs/base.md`](docs/base.md)

### Overall

| Module | Status | Completion | Details |
|---|---|---|---|
| Context Builder | Mostly done | 75% | CLAUDE.md, git context, environment, prompt assembly |
| Permission System | Partial | 55% | Pipeline, rules, interactive UI; missing AI classifier & remote approval |
| CLI | Partial | 60% | Typer app, MCP/memory sub-apps; missing 79+ commands |
| MCP Protocol | Partial | 50% | Connection, config, auth, 3 transports; missing enterprise controls |
| LLM Query Engine | Partial | 45% | Agentic loop, streaming, multi-provider; missing concurrent tool orchestration |
| TUI (Textual) | Partial | 40% | Chat app, message widgets, permissions; missing design system & Markdown |
| Config System | Partial | 40% | 3-layer settings; missing 2 layers + enterprise policy |
| Tools | Partial | 30% | 7/53+ tools done; core file ops covered |
| Hooks | Skeleton | 5% | Only `tool_permission` context factory; full lifecycle system missing |
| Memory | Skeleton | 0% | All directories empty -- file memory, AutoDream, session memory |
| Advanced Features | Not started | 0% | Coordinator, Skills, Plugins, Vim, Voice, SSH, Proactive, etc. |

### Tools: 7 / 53+ Implemented

**Done** — core file operations and MCP proxy:

| Tool | File | Notes |
|---|---|---|
| `Read` | `file_read_tool/` | File read with offset/limit, Jupyter notebook support |
| `Write` | `file_write_tool/` | Create/overwrite, auto-mkdir |
| `Edit` | `file_edit_tool/` | Exact string replacement, uniqueness check, `replace_all` |
| `Bash` | `bash_tool/` | Subprocess execution, timeout, background mode, dangerous command block |
| `Glob` | `glob_tool/` | Pattern matching, mtime sort, VCS dir exclusion |
| `Grep` | `grep_tool/` | ripgrep binary + Python fallback, multi output mode, context lines |
| `MCPTool` | `mcp_tool/` | Proxy to MCP servers, JSON Schema→Pydantic conversion |

**Skeleton** (empty directory):

| Tool | Priority |
|---|---|
| `WebFetch` | P0 |
| `WebSearch` | P0 |
| `NotebookEdit` | P0 |
| `AgentTool` (sub-agent) | P1 |

**Not started** (42+ tools): `EnterPlanMode/ExitPlanMode`, `EnterWorktree/ExitWorktree`, `TodoWrite`, `TaskCreate/Get/Update/List/Stop`, `ListMcpResources`, `ReadMcpResource`, `AskUserQuestion`, `CronCreate/Delete/List`, `TeamCreate`, `SendMessage`, `LSPTool`, `SleepTool`, `SkillTool`, `PowerShellTool`, `ToolSearchTool`, `ConfigTool`, etc.

### Slash Commands: 8 / 87+ Implemented

| Status | Commands |
|---|---|
| Done | `/help`, `/clear`, `/commit`, `/config`, `/cost`, `/mcp`, `/permissions` |
| Stub | `/compact` (command exists, but compact service not implemented) |
| Missing | `/model`, `/diff`, `/doctor`, `/init`, `/login`, `/memory`, `/plugin`, `/fast`, `/plan`, `/export`, `/hooks`, `/buddy`, `/agents`, `/bridge`, `/vim`, `/voice`, etc. |

### Key Gaps vs TypeScript Original

| Gap | Impact | Priority |
|---|---|---|
| Tool concurrent orchestration (`partitionToolCalls`) | All tools run serially; TS runs read-only tools in parallel | P0 |
| Context compaction (`compact`) | No auto-compression when nearing token limit | P0 |
| Memory system (entire) | No file memory, no AutoDream, no session memory | P1 |
| AI Bash classifier (`yoloClassifier`) | No auto-safety-classification of shell commands | P1 |
| Hooks lifecycle (20+ events) | No pre/post tool hooks, no input/output modification | P1 |
| Agent Tool (sub-agent spawning) | No multi-agent delegation | P1 |
| Multi-agent coordinator | No swarm/parallel agent execution | P2 |

### Progress at a Glance

```
Context Builder ███████████████░░░░░  75%
Permission      ███████████░░░░░░░░░  55%
CLI             ████████████░░░░░░░░  60%
MCP             ██████████░░░░░░░░░░  50%
Query Engine    █████████░░░░░░░░░░░  45%
TUI             ████████░░░░░░░░░░░░  40%
Config          ████████░░░░░░░░░░░░  40%
Tools           ██████░░░░░░░░░░░░░░  30%   (7/53+)
Hooks           █░░░░░░░░░░░░░░░░░░░   5%
Memory          ░░░░░░░░░░░░░░░░░░░░   0%
Advanced        ░░░░░░░░░░░░░░░░░░░░   0%
```

Contributions welcome — see [`docs/base.md`](docs/base.md) for the full feature-by-feature matrix.

---

## License

MIT
