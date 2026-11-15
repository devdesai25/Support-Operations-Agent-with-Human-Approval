# Architecture & Design Decisions (DECISIONS.md)

This log documents major architectural and design decisions for the Support & Operations Agent, including alternatives considered and interview-ready rationales.

---

## Milestone 1: Repository Setup, Shop Backend & Tool Layer

### ADR 1: Unified PostgreSQL Stack over Multi-Database Setup (Postgres + Neo4j / Pinecone)
* **Decision:** Use PostgreSQL for transactional shop data, policy document embeddings (`pgvector`), and agent state durability (`AsyncPostgresSaver`).
* **Alternatives Considered:** 
  1. Adding Neo4j for hybrid graph RAG.
  2. Adding Pinecone/Qdrant as a dedicated vector database.
* **Why:** The policy base contains 8–10 operational markdown documents (return windows, shipping policies, raffle rules). Graph databases shine on deep multi-hop relationship traversals across entity graphs, which is not required for document chunk search. Introducing Neo4j would add heavy JVM container overhead (1–2 GB RAM), separate backup systems, and distributed state management without performance benefit. Storing vectors, app data, and checkpoints in PostgreSQL provides atomic consistency, single-container docker deployment, and minimal operational complexity.

### ADR 2: UUID Primary Keys over Auto-Incrementing Integers
* **Decision:** Use `UUID` (v4/v7) primary keys for all public-facing domain models (`users`, `orders`, `drops`, `refunds`).
* **Alternatives Considered:** Standard auto-incrementing sequential integers (`1, 2, 3...`).
* **Why:** In an AI agent system interacting with customer accounts, sequential integers expose the system to Insecure Direct Object Reference (IDOR) enumeration attacks (an LLM or client predicting sequential IDs). Unguessable 128-bit UUIDs enforce defense-in-depth at the data layer.

### ADR 3: In-Code Authorization over Prompt-Based Instructions
* **Decision:** Tool implementations enforce `WHERE orders.user_id == current_user_id` inside SQLAlchemy queries, taking `user_id` strictly from trusted graph/session state, never from LLM-generated arguments.
* **Alternatives Considered:** Passing user ID as an LLM tool parameter or instructing the model via system prompt: *"Only access orders for user X"*.
* **Why:** Prompts cannot guarantee security boundaries. Adversarial user prompts (prompt injection, jailbreaking) can manipulate the LLM into generating arbitrary query parameters. Code-level authorization makes cross-user data leakage physically impossible in the query layer. If a user attempts to access an order belonging to someone else, the tool reports `"Order not found or access denied"` and logs a `BLOCKED` status to `agent_actions`.

### ADR 4: Idempotency Keys on Write Tools
* **Decision:** All write tools (`issue_refund`, `cancel_order`) require an `idempotency_key` and verify existence before modifying state.
* **Alternatives Considered:** Relying on LLM conversation history or web client retry logic.
* **Why:** Agent execution workflows and network networks can retry tool executions, disconnect during pauses, or double-call tools upon model restarts. Enforcing unique idempotency keys at the database and tool level guarantees that retried requests replay the original result without duplicate charges, double refunds, or contradictory state mutations.

### ADR 5: Automatic Audit Logging via `agent_actions`
* **Decision:** Every read and write tool execution records input arguments, outputs, execution time, and status (`SUCCESS`, `BLOCKED`, `ERROR`) to an `agent_actions` audit table.
* **Alternatives Considered:** Application log files (stdout/syslog) or relying solely on LangSmith tracing.
* **Why:** Financial operations and account mutations require durable, auditable, SQL-queryable compliance records. If an LLM misbehaves or an unauthorized access attempt is triggered, the audit table provides immediate non-repudiation and telemetry independent of third-party SaaS availability.
