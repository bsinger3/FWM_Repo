# CLAUDE.md — guidance for Claude Code in this repo

## Shared agent comms (read this first)

This repo is worked on by **two AI agents: Claude Code and Codex.** They share
the same checkout but have no shared memory.

- **At the start of every session, read [AGENT_LOG.md](AGENT_LOG.md)** to see
  what Codex (or a past Claude session) did and any handoffs left for you.
- **At the end of every session, append an entry to `AGENT_LOG.md`** describing
  what you changed and anything the other agent should know or avoid.
- Treat entries from Codex as **claims to verify, not ground truth.**

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
