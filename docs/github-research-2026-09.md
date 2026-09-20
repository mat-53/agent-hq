# GitHub Project Research Report — September 2026

> Research date: 2026-09-21 | Repo: C:\Users\tepeg\agent-hq | Scope: Exactly 5 projects as specified.

---

## ⚠️ Note on repo (2): `ruv-FLOW` does not exist

The URL `https://github.com/ruvnet/ruv-FLOW` returns a **404**. The repository has been renamed. The correct repo under `github.com/ruvnet` matching the description ("ruflo"/"blue flow", ~60 agents) is **`github.com/ruvnet/ruflo`** (originally called "Claude Flow", rebranded to "Ruflo"). This report covers `ruflo` as the intended target.

---

## 1. OmniRoute (`github.com/diegosouzapw/OmniRoute`)

**What it does:** OmniRoute is a free AI gateway that aggregates 352+ LLM providers (150+ with free tiers) behind a single OpenAI-compatible endpoint. It routes requests intelligently across providers with quota-aware auto-fallback, RTK + Caveman token compression (saving 15–95% tokens), and supports MCP/A2A protocols. It works as a local-first proxy that never phones home, with a Desktop/PWA interface. Built by 550+ contributors.

**Free or not:** **FREE.** MIT license. No paid tiers or API costs. The gateway itself is free; you only pay if you choose to use paid providers through it, and the project prominently catalogs ~1.62B free tokens/month across 35+ recurring pool keys. Optional sponsored-back providers exist but the core gateway is entirely free.

**Stars & activity:** ~68.6k stars, 8,982 commits. Last activity: April 2026 (v3.8.51 release branch actively maintained). Very high activity with 550+ contributors.

**Windows 11 + PowerShell:** Yes. Node.js/Next.js project with Docker support. `npx omniroute` works on Windows. Electron desktop app available. PowerShell-compatible via Node.js.

**Concrete benefit for agent-hq app:** OmniRoute would give the agent-hq app a unified routing layer across many LLM providers with automatic failover, token compression, and free-tier aggregation — reducing API costs and improving reliability. The MCP/A2A support integrates directly with agent frameworks.

**Concrete benefit for owner's terminal usage with Claude Code:** The Claude Code plugin integration means Claude Code can use OmniRoute as its model backend, getting access to 150+ free models with automatic routing. The `~1.62B free tokens/mo` dashboard is directly usable.

**Install effort:** Medium. Requires Node.js, Docker (optional), and configuration of provider keys. `npx` install is straightforward. Electron desktop app simplifies local usage.

**Risks:** Large codebase (8,982 commits) may have maintenance burden. Provider APIs change frequently (Muse Spark migration issues noted). Heavy dependency on external provider APIs. Self-hosting requires resources.

---

## 2. Ruflo (`github.com/ruvnet/ruflo`) — *originally `ruv-FLOW` / Claude Flow*

**What it does:** Ruflo is an agent meta-harness for Claude Code and Codex that adds 100+ specialized agents, coordinated swarms, self-learning memory, federated communications, and enterprise security guardrails. It acts as the execution layer — the "harness" — around AI coding agents, giving them tools, memory loops, sandboxes, and controls so they collaborate rather than just run. Features include 98 agents, 60+ commands, 30 skills, MCP server, hooks, daemon, vector memory (AgentDB/HNSW), and a web UI at flo.ruv.io.

**Free or not:** **FREE.** MIT license. The core harness is free and open-source. Optional enterprise features available at ruv.io. The web UI is self-hostable or used at flo.ruv.io (no API key needed). Some plugins may have associated costs (e.g., cloud managed agents).

**Stars & activity:** ~72.9k stars, 7,508 commits. Last activity: very active (main branch with 7,508 commits). 8.7k forks, 463 watchers. Extremely active development.

**Windows 11 + PowerShell:** Yes. `npx ruflo@latest init wizard` works natively in PowerShell and cmd. The POSIX `curl | bash` install requires Git-Bash/WSL, but the `npx` path is fully Windows-compatible. Rust core components compile on Windows.

**Concrete benefit for agent-hq app:** Ruflo's swarm coordination, memory system, and 100+ specialized agents could provide the orchestration backbone for agent-hq — enabling multi-agent workflows, persistent memory across sessions, and federated agent collaboration. The MCP server integration is directly useful.

**Concrete benefit for owner's terminal usage with Claude Code:** `npx ruflo init` gives Claude Code a "nervous system" — agents self-organize into swarms, learn from every task, remember across sessions. The 98 agents + 60+ commands significantly extend Claude Code's capabilities.

**Install effort:** Medium. `npx ruflo@latest init` is the primary install path. Full install creates `.claude/`, `.claude-flow/`, `CLAUDE.md` files. Plugin marketplace add gives lite install. More complex than a single skill install.

**Risks:** Very large codebase (7,508 commits, Rust + TypeScript + Python). The "Cognitum.One" commercial backing means direction may shift. Complex architecture may be overwhelming for simple use cases. Federation features may have security implications. The project is very ambitious and may have stability issues.

---

## 3. Ponytail (`github.com/dietrichgebert/ponytail`)

**What it does:** Ponytail makes AI agents think like "the laziest senior dev" — it encodes a YAGNI-driven coding ladder that agents follow before writing code: does it need to exist? already in codebase? stdlib does it? native feature? installed dependency? one line? Only then write the minimum. Benchmarked at ~54% less code, ~20% cheaper, ~27% faster vs no-skill baseline, with 100% safety (no cuts to validation, error handling, security, or accessibility). Works as a plugin/skill across 20+ AI coding agents.

**Free or not:** **FREE.** MIT license. No paid tiers. The entire project is open-source with no commercial version. Optional config file exists but is not required.

**Stars & activity:** ~143k stars, 224 commits. Last activity: main branch with 224 commits. Very high star count relative to commit count (indicates strong community adoption, not heavy code churn). 7.7k forks, 352 watchers.

**Windows 11 + PowerShell:** Yes. Node.js-based project. The cursor hooks install script (`node ponytail/scripts/cursor-hooks.js install`) works on Windows. `opencode.json` plugin config works cross-platform. PowerShell-compatible via Node.js. The `node` requirement must be on PATH (note for Nix/nvm users).

**Concrete benefit for agent-hq app:** Ponytail's lazy-coding philosophy directly reduces code bloat and technical debt in the agent-hq app. The benchmarked 54% code reduction and 20% cost savings translate to faster development and lower API costs. The `~20 agents` compatibility means it integrates with whatever agent framework agent-hq uses.

**Concrete benefit for owner's terminal usage with Claude Code:** Install via `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail`. Active every session with `/ponytail [lite|full|ultra|off]` commands. The ruleset injects on every prompt. Measurable impact with `/ponytail-gain`.

**Install effort:** Low. Two `/plugin` commands for Claude Code. One `node` lifecycle hook install for Cursor. Copy rules files for other agents. The least effort of all five projects for Claude Code specifically.

**Risks:** The "lazy" approach may not suit all codebases (e.g., safety-critical systems where defensive code is needed). The 54% savings benchmark is from a specific study (Haiku 4.5, n=4) and may not generalize. Some agents may resist the "one-liner" philosophy. The project is relatively young (224 commits).

---

## 4. Graphify (`github.com/Graphify-Labs/graphify`)

**What it does:** Graphify turns any codebase (code, docs, SQL schemas, configs, PDFs, images, videos) into a queryable knowledge graph. Code is parsed locally with tree-sitter AST (deterministic, no LLM, nothing leaves your machine). It produces three files: `graph.html` (clickable visualization), `GRAPH_REPORT.md` (highlights), and `graph.json` (full queryable graph). Features include god nodes, Leiden community detection, cross-file link resolution across ~40 languages, path queries, and an MCP server. Works with 20+ AI assistants via `/graphify` skill.

**Free or not:** **FREE.** MIT license (also has Apache-2.0). No paid tiers for the core tool. Optional API keys needed only if you configure a semantic backend for docs/PDFs/images (the code-only parsing is free). Optional extras like Neo4j push, Ollama, OpenAI, etc. require respective services. The project is joining Y Combinator S26 but the tool stays MIT.

**Stars & activity:** ~120k stars, 1,861 commits. Last activity: v8 branch actively maintained. 11.6k forks, 649 issues. High activity with 1,861 commits showing sustained development.

**Windows 11 + PowerShell:** Yes. Python project with `uv`/`pipx`/`pip` install. `graphify install` auto-detects Windows. The README explicitly notes PowerShell: use `graphify .` not `/graphify .`. `winget install astral-sh.uv` available. Python 3.10+ required.

**Concrete benefit for agent-hq app:** Graphify provides a knowledge graph of the entire codebase that agent-hq's AI can query instead of grepping files. The `graphify query "what connects auth to the database?"` pattern gives agents structured context. The MCP server mode (`python -m graphify.serve`) provides structured graph access. Team setup with committed `graphify-out/` ensures everyone starts with a map.

**Concrete benefit for owner's terminal usage with Claude Code:** `uv tool install graphifyy` then `graphify install` registers the skill. Type `/graphify .` in Claude Code to build and query the graph. Auto-hooks fire before Read/Glob tool calls, nudging the agent toward the graph path. The `graphify path`, `graphify explain`, `graphify query` commands are directly usable.

**Install effort:** Medium. Requires Python 3.10+ and `uv`/`pipx`. The `graphify install` command registers skills across 20+ platforms. Optional extras (PDF, office, video) require additional `uv tool install graphifyy[extra]` packages.

**Risks:** Python dependency chain may have compatibility issues on Windows. The semantic pass (for docs/PDFs) requires API keys. Large codebases may produce very large graphs (512 MiB cap). The graph may lag behind code changes if hooks aren't properly installed. The project is relatively new (Y Combinator S26) and may change direction.

---

## 5. Agent Skills (`github.com/addyosmani/agent-skills`)

**What it does:** Agent Skills provides 25 production-grade engineering skills for AI coding agents, encoding workflows, quality gates, and best practices across the entire development lifecycle: DEFINE (spec, interview-me, idea-refine) → PLAN (planning-and-task-breakdown) → BUILD (incremental-implementation, TDD, source-driven, etc.) → VERIFY (browser-testing, debugging) → REVIEW (code-review-and-quality, security, performance) → SHIP (git-workflow, CI/CD, shipping). Each skill is a structured workflow with steps, verification gates, anti-rationalization tables, and evidence requirements. Built by Addy Osmani (Google) and team, based on Google's engineering practices.

**Free or not:** **FREE.** MIT license. No paid tiers. The entire pack of 25 skills is open-source. Skills are plain Markdown — they work with any agent that accepts system prompts or instruction files. The `npx skills add` CLI is free.

**Stars & activity:** ~97.7k stars, 558 commits. Last activity: main branch with 558 commits. 10.3k forks, 512 watchers. Very high adoption (97.7k stars with relatively few commits indicates strong community validation).

**Windows 11 + PowerShell:** Yes. Markdown-based skills work everywhere. The `npx skills add addyosmani/agent-skills` command works cross-platform. Claude Code plugin install via `/plugin marketplace add addyosmani/agent-skills` works on Windows. The SSH key workaround for marketplace clones is documented for Windows/macOS.

**Concrete benefit for agent-hq app:** The 25 skills provide a complete engineering discipline framework — from spec to ship — that agent-hq's agents can follow consistently. The anti-rationalization tables and verification gates are directly applicable. The 4 agent personas (code-reviewer, test-engineer, security-auditor, web-performance-auditor) add specialized review capabilities. The `using-agent-skills` meta-skill maps incoming work to the right workflow.

**Concrete benefit for owner's terminal usage with Claude Code:** Install via `/plugin marketplace add addyosmani/agent-skills` then `/plugin install agent-skills@addy-agent-skills`. The 9 slash commands (`/spec`, `/plan`, `/build`, `/test`, `/constraints`, `/review`, `/webperf`, `/code-simplify`, `/ship`) are immediately available. Skills activate automatically based on context. The `npx skills add` CLI also works for non-Claude-Code agents.

**Install effort:** Low. `npx skills add addyosmani/agent-skills` is the fastest path. Plugin install is two `/plugin` commands. Copy skills to `.opencode/skills/` for OpenCode. Plain Markdown skills work with any agent.

**Risks:** The framework is opinionated (Google engineering culture) — may conflict with team-specific practices. The 25-skill pack is comprehensive but may be overkill for small projects. Skills are Markdown-based and don't have execution logic — they guide but don't enforce. The `npx skills` CLI dependency adds another tool to manage.

---

## Comparison Summary

| Project | Stars | License | Cost | Last Activity | Language | Agents Supported | Install Effort |
|---------|-------|---------|------|---------------|----------|-----------------|----------------|
| OmniRoute | 68.6k | MIT | Free | Apr 2026 | Node.js/TS | 6+ IDEs | Medium |
| Ruflo | 72.9k | MIT | Free | Active | TS/Rust | 6+ IDEs | Medium |
| Ponytail | 143k | MIT | Free | Active | Node.js | 20+ IDEs | Low |
| Graphify | 120k | MIT | Free | Active | Python | 20+ IDEs | Medium |
| Agent Skills | 97.7k | MIT | Free | Active | Markdown | 70+ IDEs | Low |

---

## Ranked Recommendation

### 🟢 Adopt Now

1. **Ponytail** — Lowest install effort (two `/plugin` commands for Claude Code), proven measurable impact (54% code reduction, 20% cost savings), 143k stars, MIT license, works with 20+ agents including Claude Code. Direct benefit for both agent-hq and personal Claude Code usage. The "lazy senior dev" philosophy aligns perfectly with efficient agent behavior.

2. **Agent Skills** — Complete engineering lifecycle framework (25 skills), 97.7k stars, MIT license, works with 70+ agents. The `npx skills add` CLI is the fastest install of all five. Directly applicable to agent-hq's development workflow and personal terminal usage with Claude Code's 9 slash commands. Google-engineered best practices are a strong signal.

### 🟡 Adopt Later

3. **Graphify** — Excellent for codebase awareness and queryable knowledge graphs, but requires Python 3.10+ setup and optional API keys for semantic features. Best adopted when agent-hq's codebase grows large enough to benefit from graph-based navigation. The MCP server mode is powerful but adds infrastructure complexity. Adopt after the foundation skills (Ponytail, Agent Skills) are in place.

4. **OmniRoute** — Powerful AI gateway with 352 providers and ~1.62B free tokens/month, but is a large Node.js/Next.js project that adds infrastructure overhead. Best adopted when agent-hq needs to route across multiple LLM providers with automatic failover. The complexity may be premature if a single provider suffices. Adopt when multi-provider routing becomes a necessity.

### 🔴 Skip

5. **Ruflo** — Despite 72.9k stars and ambitious features (100+ agents, swarm coordination, federation), it is a very large and complex system (7,508 commits, Rust + TypeScript + Python). The commercial backing (Cognitum.One) introduces direction uncertainty. The `npx ruflo init` approach creates significant workspace changes (`.claude/`, `.claude-flow/`, `CLAUDE.md`, helpers). For the agent-hq team's needs, Ponytail + Agent Skills cover the essential agent-guidance use cases more simply and reliably. Ruflo's value proposition (swarm coordination, federation) may become relevant at a much larger scale. Revisit when multi-machine agent orchestration is a genuine requirement.

---

## Notes on Repo (2) — `ruv-FLOW` Renamed to `ruflo`

The repository `https://github.com/ruvnet/ruv-FLOW` **does not exist** (404). The owner's project, originally called "Claude Flow," is now **`github.com/ruvnet/ruflo`**. The name change reflects the rebranding from "Claude Flow" to "Ruflo" (named by rUv, combining Rust + flow). The project has 72.9k stars, 7,508 commits, and offers 100+ specialized agents with swarm coordination, self-learning memory, and federated communications. It is MIT-licensed and free.

---

*Report generated by research agent. All data sourced from GitHub repository pages as of September 2026.*
