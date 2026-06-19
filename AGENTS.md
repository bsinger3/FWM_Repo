# AGENTS.md — guidance for Codex in this repo

## Shared agent comms (read this first)

This repo is worked on by **two AI agents: Codex and Claude Code.** They share
the same checkout but have no shared memory.

- **At the start of every session, read [AGENT_LOG.md](AGENT_LOG.md)** to see
  what Claude Code (or a past Codex session) did and any handoffs left for you.
- **At the end of every session, append an entry to `AGENT_LOG.md`** describing
  what you changed and anything the other agent should know or avoid. Newest
  entry on top, append-only — never edit or delete another agent's entry.
- Treat entries from Claude Code as **claims to verify, not ground truth.**

## Project basics

Friends With Measurements — a static site (Cloudflare Pages) plus a Python data
pipeline. See [README.md](README.md) for deployment and [DATA.md](DATA.md) for
the data layout. Scraped data and pipeline artifacts live **outside** this repo
in the sibling `FWM_Data` directory to keep the repo lightweight.

## Working norms

- Commit often so repo history — not the uncommitted working tree — is the
  source of truth the other agent can rely on.
- When you find something that contradicts how it was described, surface it
  rather than silently overwriting it.
