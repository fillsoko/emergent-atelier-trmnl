# Emergent Atelier — Blog Content Strategy

## Voice & Tone

**Voice:** Founder energy meets technical honesty. We're builders who are genuinely excited about what we're making — not hype merchants. We explain *why* things work the way they do, not just what they are.

**Tone calibration:**
- Excited, but grounded — no vague "AI-powered" fluff
- Technical without being impenetrable — assume readers can read code but may not know ML internals
- Personal — this is a project with humans and agents behind it, not a faceless product
- Curious — we don't have all the answers, and that's part of the fun

**What we avoid:**
- Buzzword bingo ("revolutionary", "game-changing", "disruptive")
- Passive voice
- Walls of text with no structure
- Over-promising

---

## Post Frequency

**Weekly.** Every Thursday. Short is fine — 300 words beats a 1,200-word post that ships three weeks late.

---

## Post Types

### 1. Project Updates
What shipped, what changed, what broke and got fixed. Transparent and specific. Link to commits and issues where relevant.

### 2. Behind-the-Scenes
How decisions get made. Architecture trade-offs. Why we picked eInk. What it's like to have AI agents collaborating on code and art simultaneously.

### 3. Release Notes
Structured changelog-style posts for named releases. What's new, what's removed, migration notes if needed.

### 4. Community Highlights
Showcasing forks, custom agents, art outputs, and contributions from the community. Credit generously.

---

## Standard Frontmatter

Every post must use this frontmatter format:

```yaml
---
title: "Post Title"
date: YYYY-MM-DD
author: "Agent Name"  # or human name
excerpt: "One sentence summary shown in post listings."
tags: [update, release, community]
---
```

**Available tags:** `update`, `release`, `community`, `architecture`, `behind-the-scenes`, `tutorial`, `announcement`

---

## Content Principles

1. **Show, don't tell.** Code snippets, screenshots, GIFs of the canvas evolving — always prefer concrete over abstract.
2. **Be honest about limitations.** If something doesn't work perfectly yet, say so. Readers respect transparency.
3. **Link richly.** Point to the repo, to specific files, to related posts. The blog should be a map into the project.
4. **Keep it skimmable.** Use headers, bullets, and code blocks. Dense paragraphs belong in academic papers.
5. **End with a hook.** What's coming next? What can readers try today?
