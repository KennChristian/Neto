# Verification Agent Creator

> **Purpose:** Standalone prompt that generates a project-specific verification-audit-agent. Paste this into a Claude Code session to autonomously explore the codebase, interview the user for domain knowledge, and assemble a fully configured agent.
>
> **Prerequisites:** A code repository with some existing source files. The `claude-harness/` directory (or its templates) must be accessible.
>
> **Independence:** This prompt works independently of the bootstrap prompt. It does not assume any prior setup — it discovers everything it needs via codebase exploration.

---

## Instructions for Claude

Follow these 5 phases in order. Each phase builds on the previous one's output. Show the user what you've discovered at each phase and get confirmation before proceeding.

---

## Phase 1: Autonomous Codebase Exploration

Gather as much information as possible from the codebase before asking the user anything.

### Steps

1. **Detect project fundamentals:**
   - Read `CLAUDE.md` (root and any subdirectory CLAUDE.md files) for project identity, tech stack, and conventions
   - Read `package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `docker-compose.yml` — whichever exist
   - Identify: programming language(s), framework(s), database(s), infrastructure, test framework

2. **Map the directory structure:**
   - Scan directories at depth 2 to understand the project layout
   - Identify major subsystems and their roles
   - Note any existing MANIFEST.md files for quick file-role mapping

3. **Identify design patterns and conventions:**
   - Launch an Explore agent to find: base classes, interfaces, abstract classes, mixins, decorators, middleware
   - Look for: error handling patterns, configuration patterns, access control mechanisms
   - Identify the project's primary architectural pattern (MVC, hexagonal, microservices, monolith, etc.)

4. **Map module boundaries and integration points:**
   - Launch an Explore agent to find: cross-module imports, API boundaries, database access layers, external service clients
   - Identify system boundaries: where does this project talk to external systems (databases, APIs, message queues, file systems)?
   - Note any data flow patterns (e.g., ingest → process → store → serve)

5. **Catalog test infrastructure:**
   - Find test directories and test files
   - Identify the test runner and test commands
   - Note any test fixtures, factories, or mock patterns

6. **Build project profile:**

   Assemble discoveries into a structured profile:

   ```
   ## Project Profile

   ### Identity
   - Name: {detected}
   - Description: {from CLAUDE.md or inferred}

   ### Tech Stack
   - Language(s): {detected}
   - Framework(s): {detected}
   - Database(s): {detected}
   - Infrastructure: {detected}
   - Test framework: {detected}

   ### Architecture
   - Pattern: {MVC/hexagonal/microservices/etc.}
   - Module structure: {how code is organized}
   - Key design patterns: {patterns found}

   ### Directory Map
   | Directory | Concern |
   |-----------|---------|
   | `src/...` | ... |

   ### Integration Points
   - {database type} access via {ORM/client}
   - {external service} integration
   - {API/file/queue} boundaries

   ### Test Infrastructure
   - Runner: {test command}
   - Fixtures: {location}
   - Patterns: {mocking strategy}
   ```

7. **Present the profile to the user** for confirmation and correction.

---

## Phase 2: Outcome-Oriented Interview

Ask the user only what cannot be inferred from code. Focus on outcomes and domain knowledge, not technical details.

### Steps

1. **Present the project profile** from Phase 1 and ask: "Is this accurate? Anything to add or correct?"

2. **Ask outcome-oriented questions** using the AskUserQuestion tool. Ask 2-3 questions at a time, with multiple-choice options where possible:

   **Question set 1: Verification priorities**
   - "What outcomes matter most when verifying work on this project?" Options:
     - Data integrity (correct transformations, no data loss)
     - API contracts (endpoints behave as documented)
     - UI correctness (components render and interact properly)
     - Performance (response times, resource usage)
     - Security (access control, input validation)
     - Other (describe)

   **Question set 2: Domain invariants**
   - "What are the critical data integrity rules that must never be violated?" (free text)
   - "What failure modes have caused problems before?" (free text)

   **Question set 3: Domain knowledge**
   - "What domain-specific terminology should the agent understand?" (free text)
   - "Are there domain-specific data flows or business rules that aren't obvious from the code?" (free text)

3. **Synthesize answers** into domain knowledge subsections for the agent template.

---

## Phase 3: Scenario Generation

Using Phase 1 discoveries and Phase 2 answers, generate all project-specific content for the templates.

### Steps

1. **Generate agent identity:**
   - Craft `{AGENT_IDENTITY}`: A role identity line that reflects the project's domain
     - Format: "You are the Verification & Outcome Audit Agent — an elite [role] specializing in [domain areas]."
     - Example: "You are the Verification & Outcome Audit Agent — an elite full-stack quality assurance architect specializing in real-time data pipelines, React component systems, and distributed service validation."

2. **Generate domain expertise:**
   - Craft `{AGENT_DOMAIN_EXPERTISE}`: A paragraph listing specific technologies and tools
     - Format: "Your domain expertise spans: [comma-separated list of technologies, frameworks, tools, and domain concepts]."

3. **Generate codebase map:**
   - Craft `{PROJECT_CODEBASE_MAP}`: Indented list items mapping directories to concerns
     - Format: Each line is `   - \`directory/\` for [concern] changes`
     - Include 4-8 key directories from the Phase 1 directory map

4. **Generate integration points:**
   - Craft `{PROJECT_INTEGRATION_POINTS}`: Indented list items for Phase 4 step 3
     - Format: Each line is `   - [System boundary description]`
     - Reference actual technologies discovered (e.g., "PostgreSQL queries via Django ORM", "REST API responses")

5. **Generate code patterns:**
   - Craft `{PROJECT_CODE_PATTERNS}`: Comma-separated list of design patterns
     - Example: "repository pattern, dependency injection, middleware chain"

6. **Generate module structure:**
   - Craft `{PROJECT_MODULE_STRUCTURE}`: Reference to the primary code organization
     - Example: "`src/features/` feature-based module structure"

7. **Generate domain knowledge:**
   - Craft `{PROJECT_DOMAIN_KNOWLEDGE}`: Markdown subsections under "Project-Specific Knowledge"
     - Each subsection is `### [Topic]\n[1-3 sentences]`
     - Include 2-4 subsections based on Phase 2 interview answers
     - Focus on invariants, data flows, and domain rules

8. **Generate memory examples:**
   - Craft `{PROJECT_MEMORY_EXAMPLES}`: Additional bullet points for the memory recording list
     - Format: Each line is `- [What to record about this project]`
     - Include 2-4 project-specific suggestions based on tech stack and domain

9. **Generate description examples:**
   - Fill all 10 description placeholders using actual project artifacts:
     - `{EXAMPLE_1_CONTEXT}` through `{EXAMPLE_4_USER_MSG}` — each grounded in real directories, models, and workflows from Phase 1
     - Cover different parts of the codebase across the 4 examples
     - User messages should sound natural

10. **Present all generated content** to the user for review before assembly.

---

## Phase 4: Agent Assembly

Assemble the final agent file from templates and generated content.

### Steps

1. **Read the agent template:**
   - Read `claude-harness/modules/verification/templates/verification-audit-agent.md` (or locate it in the accessible path)
   - Extract the Agent Body section (between the markdown code fence)

2. **Read the description template:**
   - Read `claude-harness/modules/verification/templates/verification-audit-agent-description.md`
   - Extract the Description Field Value section

3. **Fill description placeholders:**
   - Replace all 10 `{EXAMPLE_*}` placeholders with content from Phase 3 step 9
   - Escape the result for YAML: replace newlines with `\\n`, escape quotes

4. **Fill agent body placeholders:**
   - Replace all 9 `{PLACEHOLDER}` markers with content from Phase 3 steps 1-8
   - `{AGENT_DESCRIPTION}` ← the escaped description string from step 3

5. **Assemble the final file:**
   - Combine YAML frontmatter + filled agent body
   - The YAML frontmatter fields are: `name`, `description`, `model`, `color`, `memory`

6. **Write the agent file:**
   - Write to `.claude/agents/verification-audit-agent.md`
   - Create `.claude/agents/` directory if it doesn't exist

7. **Create memory directory:**
   - Create `.claude/agent-memory/verification-audit-agent/` directory
   - Do NOT create a MEMORY.md — the agent will create its own on first use

---

## Phase 5: Validation

Verify the generated agent is correct and functional.

### Steps

1. **Present the generated agent** to the user:
   - Show the YAML frontmatter
   - Show the first few sections of the agent body
   - Highlight the project-specific content that was filled in

2. **Run validation checks:**
   - Verify YAML frontmatter has all required fields (`name`, `description`, `model`, `color`, `memory`)
   - Verify no unfilled `{PLACEHOLDER}` markers remain in the agent body
   - Verify no project-generic template instructions leaked into the output
   - Verify the agent file is valid markdown

3. **Offer a dry-run:**
   - Ask: "Want me to use the new verification-audit-agent to verify a recent piece of work as a test?"
   - If yes, invoke the agent via the Agent tool with `subagent_type` set to the agent name
   - Review the agent's output for quality and relevance

4. **Adjust based on feedback:**
   - If the user wants changes, edit the agent file directly
   - Common adjustments: tone of identity line, additional domain knowledge, different example scenarios

5. **Confirm completion:**
   ```
   ## Verification Agent Created

   ### Files:
   - `.claude/agents/verification-audit-agent.md` — Agent prompt
   - `.claude/agent-memory/verification-audit-agent/` — Memory directory (empty, populates on use)

   ### The agent will be invoked:
   - Automatically during plan execution (orchestration step 9)
   - Proactively when vague instructions, complex tasks, or post-implementation audits are detected
   - Explicitly when you ask: "use the verification-audit-agent to check this"

   ### To regenerate:
   Run this creator prompt again in a new session.
   ```
