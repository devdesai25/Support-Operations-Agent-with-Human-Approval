import asyncio
import hashlib
import math
from pathlib import Path
import re
from typing import Any
import uuid
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory, init_db
from app.models.policy import PolicyChunk

POLICIES_DIR = Path(__file__).resolve().parent / "policies"
EMBEDDING_DIM = 128


def compute_deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Compute a deterministic, normalized term-frequency embedding vector.
    
    Ensures policy semantic search works reliably in tests, CI, and offline
    environments without requiring external paid API keys.
    """
    words = re.findall(r"\w+", text.lower())
    if not words:
        return [0.0] * dim

    vec = [0.0] * dim
    for word in words:
        # Use md5 hash to project word into vector dimensions
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        slot = h % dim
        sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
        vec[slot] += sign

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [round(x / norm, 6) for x in vec]
    return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two normalized vectors."""
    if len(vec_a) != len(vec_b):
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b, strict=False))


def chunk_markdown_file(file_path: Path) -> list[dict[str, Any]]:
    """Parse a markdown policy document into distinct logical sections."""
    text = file_path.read_text(encoding="utf-8")
    doc_name = file_path.name
    doc_title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    doc_title = doc_title_match.group(1).strip() if doc_title_match else file_path.stem

    # Split by section header (##)
    sections = re.split(r"(?m)^##\s+", text)
    chunks = []
    chunk_idx = 0

    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue

        lines = sec.splitlines()
        first_line = lines[0].strip()

        # If it's the preamble before the first ##, use doc_title
        if first_line.startswith("#"):
            section_title = doc_title
            content = "\n".join(lines[1:]).strip()
        else:
            section_title = first_line
            content = "\n".join(lines[1:]).strip()

        if not content:
            continue

        full_content_to_embed = f"{doc_title} - {section_title}: {content}"
        embedding = compute_deterministic_embedding(full_content_to_embed)

        chunks.append({
            "doc_name": doc_name,
            "chunk_index": chunk_idx,
            "title": f"{doc_title} - {section_title}",
            "content": content,
            "metadata_json": {
                "source": doc_name,
                "section": section_title,
                "embedding": embedding,
            },
        })
        chunk_idx += 1

    return chunks


async def index_all_policies(session: AsyncSession) -> int:
    """Read markdown policies, chunk them, and store in policy_chunks table."""
    # Delete existing indexed chunks
    await session.execute(delete(PolicyChunk))

    files = list(POLICIES_DIR.glob("*.md"))
    total_indexed = 0

    for file_path in files:
        chunks = chunk_markdown_file(file_path)
        for c in chunks:
            chunk_obj = PolicyChunk(
                doc_name=c["doc_name"],
                chunk_index=c["chunk_index"],
                title=c["title"],
                content=c["content"],
                metadata_json=c["metadata_json"],
            )
            session.add(chunk_obj)
            total_indexed += 1

    await session.commit()
    return total_indexed


async def main() -> None:
    await init_db()
    async with async_session_factory() as session:
        indexed_count = await index_all_policies(session)
        print(f"Successfully indexed {indexed_count} policy chunks into policy_chunks.")


if __name__ == "__main__":
    asyncio.run(main())
