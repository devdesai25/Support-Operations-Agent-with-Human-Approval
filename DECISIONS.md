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

---

## Milestone 2 & Milestone 3: LangGraph Agent Core, Policy RAG & LangSmith Tracing

### ADR 6: Structured Output Intent Classification with Resilient Heuristic Fallback
* **Decision:** Implement `classify_intent` with Pydantic structured output (`model.with_structured_output(IntentClassification)`) alongside a deterministic keyword/regex heuristic classifier.
* **Alternatives Considered:** Open-ended conversational prompt routing, or multiple independent routing agents.
* **Why:** Structured output guarantees type safety and schema validation for downstream conditional edges (`route_intent`). Providing a deterministic fallback enables ultra-fast, zero-cost, network-independent unit tests and CI runs while giving production instances graceful degradation if model APIs experience outages.

### ADR 7: Single Consolidated Read-Only Node over Multiple Specialist Agents
* **Decision:** Use a single `read_tools` node responsible for executing read lookups (`get_order`, `list_user_orders`, `get_drop_entry_status`, `search_policies`) based on state.
* **Alternatives Considered:** Spawning separate subagents or separate nodes for each individual tool.
* **Why:** Rule 5 ("Simple and correct over clever"). Creating separate subagents or 4 discrete nodes for read-only lookups causes unnecessary state graph complexity, higher execution latency, and additional serialization overhead without any operational benefit. A single node with deterministic dispatch is easy to debug, test, and defend.

### ADR 8: Policy RAG with Mandatory Source Attribution
* **Decision:** Implement `search_policies` to chunk operational markdown policies, compute normalized vector embeddings, calculate cosine similarities, and return source filenames with every result.
* **Alternatives Considered:** Inlining policy text into system prompts.
* **Why:** Inlining policies in system prompts balloons context window tokens, increases per-query latency and API costs, and increases hallucination risks. RAG retrieves only the top relevant chunks on-demand. Returning source attribution (`return_policy.md`, etc.) allows the agent and customer to verify the authoritative basis for operational answers.

### ADR 9: Session Dependency Injection via `RunnableConfig`
* **Decision:** Pass database sessions into node executions using LangGraph's standard `config["configurable"]["session"]`, falling back to `async_session_factory()`.
* **Alternatives Considered:** Global session variables or recreating connection pools per node.
* **Why:** Follows official LangGraph runtime configuration standards. It decouples graph nodes from specific database instances, allowing test suites to inject isolated in-memory SQLite transactions while allowing FastAPI request lifecycles to inject transactional PostgreSQL sessions cleanly.

### ADR 10: Zero-Overhead LangSmith Tracing Integration
* **Decision:** Enable LangSmith tracing natively via standard environment flags (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT`) without custom wrapper code.
* **Alternatives Considered:** Custom logging middleware or manual OpenTelemetry spans on every node.
* **Why:** LangGraph and LangChain natively instrument every graph transition, state diff, LLM latency, and token count when environment variables are set. Relying on the official tracer ensures 100% telemetry fidelity with zero invasive boilerplate.

---

## Milestone 4, Milestone 5 & Milestone 6: Human Approval, Guardrails, and Eval Suite

### ADR 11: Human-in-the-Loop via Native `interrupt()` and `Command(resume=...)`
* **Decision:** Implement approval gates inside `approval_gate_node` using LangGraph v0.2+ `interrupt()`, resumed via `Command(resume=payload)`.
* **Alternatives Considered:** Custom database polling loops or external message queues (Celery/RabbitMQ).
* **Why:** `interrupt()` is LangGraph's first-class primitive for pausing execution graphs. It serializes the exact execution frame to the configured checkpointer, yields control to external clients, and cleanly resumes upon receiving `Command(resume=...)`. This eliminates brittle polling workers and custom state-machine orchestrators.

### ADR 12: Durable Checkpoint Durability across Process Restarts
* **Decision:** Checkpoint state via `AsyncPostgresSaver` (and `AsyncSqliteSaver` in test environments) with an automated test proving a paused run survives a simulated server shutdown.
* **Alternatives Considered:** Memory-only checkpointing or Redis caching.
* **Why:** Support tickets requiring supervisor approval can sit idle for minutes, hours, or overnight. In production Kubernetes/Docker environments, containers restart frequently during deployments. In-memory state would lose all waiting approvals; database-backed checkpointing guarantees zero lost state across container lifecycle events.

### ADR 13: Hard Code-Enforced Preconditions in `execute_action`
* **Decision:** `execute_action_node` checks `approval_status == 'approved'` in Python code before calling write tools, refusing execution if unapproved.
* **Alternatives Considered:** Relying on graph routing edges alone to prevent unauthorized execution.
* **Why:** Defense-in-depth. If an adversarial prompt injection or a developer edge-routing bug accidentally directs execution to `execute_action`, the node itself acts as a zero-trust barrier and halts execution.

### ADR 14: Defense-in-Depth Guardrails
* **Decision:** Enforce `MAX_STEPS = 10`, loop detection, token cost estimation, and input regex/delimiter sanitization in `app/agent/guardrails.py`.
* **Alternatives Considered:** Third-party guardrail frameworks (NeMo Guardrails, Guardrails AI).
* **Why:** Third-party guardrail frameworks add heavy dependencies and latency. A compact, explicit module covering control character stripping, injection delimiter detection, step limits, and cost caps provides immediate protection without black-box complexity.

### ADR 15: Quantitative Evaluation Architecture with Hard Invariants
* **Decision:** Implement `evals/run.py` over 50 real-world customer tickets measuring Routing Accuracy, Tool-Call Correctness, Approval-Gate Correctness, Policy Compliance, Steps, Latency, and Cost.
* **Alternatives Considered:** Unstructured manual spot-checking or subjective qualitative prompt grading.
* **Why:** Engineering jobs require verifiable metrics. Treating "Approval-Gate Correctness" as an absolute invariant (100% required, 0% write actions allowed without human approval) proves the system meets enterprise financial compliance standards.
