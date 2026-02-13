# Claude Code Skills Tutorial: Customization with Skills

This tutorial teaches you how to create and use **skills** in Claude Code -- the primary way to extend Claude with custom capabilities, workflows, and knowledge.

## What are skills?

Skills are reusable instruction sets that teach Claude new capabilities. Each skill is a markdown file (`SKILL.md`) containing instructions Claude follows when the skill is activated. You invoke them as slash commands (e.g., `/my-skill`) or Claude can auto-invoke them based on context.

Skills follow the [Agent Skills open standard](https://agentskills.io), making them portable across AI tools.

### Skills vs. other customization methods

| Method | Purpose | Loaded when |
|--------|---------|-------------|
| **Skills** | Teach Claude new capabilities | On invocation (manual or auto) |
| **CLAUDE.md** | Persistent project context and rules | Every session, automatically |
| **Hooks** | Run shell commands at lifecycle events | Automatically at trigger events |

**Rule of thumb:** Use skills for *things Claude can do*, CLAUDE.md for *things Claude should know*, and hooks for *things that must always happen*.

---

## Part 1: Your first skill

### File structure

Every skill lives in its own directory with a `SKILL.md` file:

```
.claude/skills/my-skill/
  SKILL.md          # Required: instructions + metadata
  template.txt      # Optional: supporting files
  examples/         # Optional: example outputs
```

Skills can be stored in two locations:

| Location | Scope |
|----------|-------|
| `~/.claude/skills/<name>/` | Personal -- applies to all your projects |
| `.claude/skills/<name>/` | Project -- shared via version control |

### Create a "hello world" skill

1. Create the directory:

```bash
mkdir -p .claude/skills/greet
```

2. Create `.claude/skills/greet/SKILL.md`:

```markdown
---
name: greet
description: Greet the user and summarize the current project
---

When invoked, do the following:

1. Greet the user warmly
2. Read the project's README or main entry point
3. Provide a 2-3 sentence summary of what this project does
4. List the top 3 files the user might want to work on
```

3. Use it in Claude Code:

```
> /greet
```

Claude reads the skill instructions and executes them.

---

## Part 2: Skill anatomy -- the SKILL.md file

Every `SKILL.md` has two parts: **YAML frontmatter** (metadata) and **markdown body** (instructions).

### Frontmatter reference

```yaml
---
name: deploy-staging
description: Deploy the current branch to the staging environment
disable-model-invocation: true
allowed-tools: Bash, Read
argument-hint: [environment]
---
```

| Field | Default | Description |
|-------|---------|-------------|
| `name` | directory name | Slash command name (lowercase, hyphens, max 64 chars) |
| `description` | -- | What the skill does. Claude uses this to decide auto-invocation |
| `disable-model-invocation` | `false` | If `true`, only manual `/name` invocation works |
| `user-invocable` | `true` | If `false`, hidden from `/` menu; only Claude can invoke it |
| `allowed-tools` | -- | Tools Claude can use without asking: `Read, Grep, Bash, Edit, Write, Glob` |
| `model` | current model | Override the model for this skill |
| `context` | -- | Set to `fork` to run in an isolated subagent |
| `agent` | -- | Subagent type: `Explore`, `Plan`, `general-purpose` |
| `argument-hint` | -- | Autocomplete hint shown in the `/` menu |
| `hooks` | -- | Lifecycle hooks scoped to this skill |

### Markdown body

The body contains the actual instructions Claude follows. Write them as clear, step-by-step directions:

```markdown
---
name: code-review
description: Review code changes for quality and correctness
---

Review the current staged changes (or the files specified in $ARGUMENTS):

1. **Read the diff** using `git diff --staged` (or read the specified files)
2. **Check for bugs**: logic errors, off-by-one mistakes, null references
3. **Check style**: naming conventions, code organization, consistency
4. **Check security**: injection risks, credential exposure, input validation
5. **Summarize** findings in a numbered list, sorted by severity
```

---

## Part 3: Dynamic content

Skills support variable substitution and dynamic shell output for flexible, context-aware behavior.

### Argument substitution

| Variable | Description |
|----------|-------------|
| `$ARGUMENTS` | All arguments passed after the command |
| `$1`, `$2`, ... | Individual positional arguments |
| `${CLAUDE_SESSION_ID}` | Current session identifier |

**Example -- a skill that fixes a GitHub issue:**

```markdown
---
name: fix-issue
description: Analyze and fix a GitHub issue by number
argument-hint: [issue-number]
---

Fix GitHub issue #$ARGUMENTS:

1. Fetch the issue details with `gh issue view $ARGUMENTS`
2. Understand the reported problem
3. Find the relevant code
4. Implement the fix
5. Write tests covering the fix
6. Commit with message: "fix: resolve issue #$ARGUMENTS"
```

Usage: `/fix-issue 42`

### Shell command injection

Prefix a backtick-command with `!` to run it *before* Claude sees the skill. The output replaces the command inline:

```markdown
---
name: pr-review
description: Review the current pull request
---

## Context

Current branch: !`git branch --show-current`
Changed files:
!`git diff --name-only main`

## Instructions

Review each changed file for correctness, style, and security.
```

When invoked, Claude sees the actual branch name and file list -- not the commands.

---

## Part 4: Controlling invocation

You can fine-tune *who* can trigger a skill:

### Manual-only skills

For sensitive operations (deploys, destructive actions), restrict to manual invocation:

```yaml
---
name: deploy-prod
description: Deploy to production
disable-model-invocation: true
---
```

Now only `/deploy-prod` works. Claude will never trigger it on its own.

### Claude-only skills

For background helpers Claude uses as needed:

```yaml
---
name: style-enforcer
description: Apply project style conventions when writing code
user-invocable: false
---
```

This skill won't appear in your `/` menu, but Claude loads it automatically when writing code.

### Summary

| Setting | You type `/skill` | Claude auto-invokes |
|---------|:-:|:-:|
| (defaults) | Yes | Yes |
| `disable-model-invocation: true` | Yes | No |
| `user-invocable: false` | No | Yes |

---

## Part 5: Running skills in subagents

For research-heavy or isolated tasks, run a skill in a forked context so it doesn't clutter your main conversation:

```yaml
---
name: deep-dive
description: Thoroughly research a topic in the codebase
context: fork
agent: Explore
---

Research "$ARGUMENTS" in this codebase:

1. Find all relevant files and definitions
2. Trace the data flow end-to-end
3. Identify edge cases and potential issues
4. Return a structured summary
```

The `context: fork` setting runs the skill in a subagent. The result is returned to your main session as a single summary.

---

## Part 6: Practical skill examples

### 1. Commit helper

```markdown
---
name: commit
description: Stage and commit changes with a conventional commit message
disable-model-invocation: true
allowed-tools: Bash, Read
---

1. Run `git status` and `git diff` to understand all changes
2. Group related changes logically
3. Write a conventional commit message:
   - Type: feat, fix, refactor, docs, test, chore
   - Scope: the area of the codebase affected
   - Description: what and why (not how)
4. Stage the relevant files (prefer specific files over `git add .`)
5. Create the commit
```

### 2. Test writer

```markdown
---
name: write-tests
description: Generate tests for a given file or function
argument-hint: [file-path]
allowed-tools: Read, Write, Bash, Grep
---

Write tests for $ARGUMENTS:

1. Read the source file to understand its behavior
2. Identify all public functions and edge cases
3. Check for an existing test file; create one if needed
4. Write tests covering:
   - Happy path for each function
   - Edge cases (empty input, nulls, boundaries)
   - Error conditions
5. Run the tests and fix any failures
```

### 3. Documentation generator

```markdown
---
name: document
description: Generate documentation for a module or file
argument-hint: [file-path]
context: fork
agent: general-purpose
---

Document $ARGUMENTS:

1. Read the file and understand its purpose
2. Identify all exports, classes, and public functions
3. Generate a markdown doc with:
   - Overview paragraph
   - Function signatures with parameter descriptions
   - Usage examples
   - Notes on edge cases or gotchas
```

### 4. Security review

```markdown
---
name: security-check
description: Review pending changes for security vulnerabilities
allowed-tools: Bash, Read, Grep
---

Review the current changes for security issues:

1. Get the diff: `git diff` and `git diff --staged`
2. Check for OWASP Top 10 vulnerabilities:
   - Injection (SQL, command, template)
   - Broken authentication
   - Sensitive data exposure (hardcoded secrets, credentials)
   - XSS (cross-site scripting)
   - Insecure deserialization
3. Flag any issues with severity (critical/high/medium/low)
4. Suggest specific fixes for each finding
```

---

## Part 7: Sharing skills with your team

### Project-scoped skills

Commit `.claude/skills/` to version control so every team member gets the same skills:

```bash
git add .claude/skills/
git commit -m "feat: add shared Claude Code skills"
```

### Personal skills

Keep private skills in `~/.claude/skills/` -- these are not version-controlled and apply to all your projects.

### Organizing skills

A mature project might look like:

```
.claude/
  skills/
    commit/SKILL.md           # Git workflow
    write-tests/SKILL.md      # Test generation
    deploy-staging/SKILL.md   # Staging deploys
    security-check/SKILL.md   # Security review
    fix-issue/SKILL.md        # GitHub issue workflow
```

---

## Part 8: Tips and best practices

1. **Write clear descriptions.** The `description` field is how Claude decides whether to auto-invoke your skill. Be specific about *when* it should be used.

2. **Keep instructions actionable.** Write numbered steps with concrete actions. Vague instructions produce vague results.

3. **Use `disable-model-invocation: true` for anything destructive.** Deploys, database migrations, and bulk operations should require explicit invocation.

4. **Use `context: fork` for research tasks.** This keeps your main conversation clean and prevents long research from consuming your context window.

5. **Prefer project skills over personal skills for team workflows.** If the whole team benefits, commit it to `.claude/skills/`.

6. **Use `allowed-tools` to grant permissions.** This avoids repeated permission prompts during skill execution.

7. **Test iteratively.** Start simple, invoke the skill, observe the result, and refine the instructions.

8. **Use argument hints.** The `argument-hint` field improves discoverability when team members browse the `/` menu.

---

## Quick reference

```
# Create a skill
mkdir -p .claude/skills/my-skill
# Edit .claude/skills/my-skill/SKILL.md

# Invoke a skill
> /my-skill
> /my-skill arg1 arg2

# Check loaded skills
> /context

# Skill file template
---
name: my-skill
description: What it does and when to use it
---

Step-by-step instructions here.
```

---

## Next steps

- Try creating a simple skill for a repeated task in your workflow
- Explore the built-in `/init` skill to set up your project's `CLAUDE.md`
- Read the [official skills documentation](https://docs.anthropic.com/en/docs/claude-code/skills) for the full reference
- Check out the [Agent Skills standard](https://agentskills.io) for cross-tool compatibility
