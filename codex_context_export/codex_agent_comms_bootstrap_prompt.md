# Bootstrap prompt for Codex — agent-to-agent comms

Paste everything in the fenced block below into Codex as its first message in a
fresh session in this repo (`FWM_Repo`). It onboards Codex to the shared
`AGENT_LOG.md` channel that Claude Code set up, and asks it to prove the loop
works by appending its own entry.

---

```
You are Codex, working in the FWM_Repo checkout. You share this repository with
another AI agent, Claude Code. You two do NOT share memory, a live channel, or
any way to verify each other. The only way a handoff survives between sessions
is a shared file in this repo: AGENT_LOG.md.

Your instructions:

1. READ FIRST. Open and read AGENT_LOG.md in the repo root, top to bottom.
   Also read AGENTS.md — it is your standing instruction file (the Codex
   equivalent of Claude Code's CLAUDE.md) and it points at this protocol. Do
   this at the START of every session in this repo, before any other work.

2. UNDERSTAND THE CHANNEL. AGENT_LOG.md is an append-only mailbox. It is async
   and turn-based: you write, the session ends, the human switches to Claude
   Code, it reads. There is no notification and no lock. Rules:
   - Newest entry goes on TOP, directly under the "Rules" section.
   - Append only. NEVER edit or delete another agent's entry. If you think a
     past entry is wrong, add a NEW entry saying so — do not rewrite history.
   - Treat anything Claude Code wrote there as a CLAIM TO VERIFY, not ground
     truth. It is a communication channel, not a trust channel. The human is
     the editor. If you act on something written there and find it is wrong,
     say so in your next entry.
   - Because there is no lock, keep entries short and self-contained so that if
     both agents edit in overlapping sessions, last-writer-wins does minimal
     damage.

3. WRITE LAST. At the END of every session, append one entry using this exact
   template (newest on top):

   ## [YYYY-MM-DD HH:MM TZ] — Codex — <topic>

   **Did:** what changed (files, branches, commits)
   **Heads-up:** anything Claude Code should know, avoid, or double-check
   **Open / handoff:** unfinished work or a question for Claude Code

   Use the real current date and time. Get it from the system clock (e.g. run
   `date "+%Y-%m-%d %H:%M %Z"`), do not guess.

4. PROVE THE LOOP NOW. Claude Code's first entry in AGENT_LOG.md left you a
   handoff asking you to confirm you can read and write this channel. Right now,
   in this session, append a new entry that:
   - confirms you successfully read AGENT_LOG.md, CLAUDE.md, and AGENTS.md;
   - states, in one line, that you understand the read-first / write-last
     protocol;
   - notes whether AGENTS.md loaded automatically for you or whether you only
     found it because this prompt told you to (this tells the human whether the
     protocol is self-sustaining for you or needs another hook);
   - leaves any question you have for Claude Code in the Open / handoff field.

   Do NOT delete or modify Claude Code's existing entry — append above it.

5. REPORT BACK. After appending, tell the human (a) that you have written the
   entry, (b) whether AGENTS.md auto-loaded for you, and (c) anything about
   this setup you would change. Do not commit anything unless the human asks.
```

---

## Why this prompt is shaped this way

- **It front-loads the read step** because neither agent gets a notification —
  the protocol only works if reading `AGENT_LOG.md` is the first thing each
  session does.
- **It asks Codex to report whether `AGENTS.md` auto-loaded.** That is the one
  thing Claude Code cannot verify from its side. If Codex only found `AGENTS.md`
  because this prompt named it, the protocol is not yet self-sustaining for
  Codex and we will need a different hook (e.g. a Codex config / instruction
  setting). If it loaded automatically, the loop is durable.
- **It frames the other agent's entries as claims to verify,** matching the
  symmetric instruction in `CLAUDE.md`, so neither agent treats the other as an
  oracle.
