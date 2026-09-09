from __future__ import annotations

import json
from pathlib import Path

from app.retrieval import retrieval_service

DATASET = Path(__file__).with_name("eval_dataset.json")


def evaluate(mode: str, top_k: int = 3) -> dict:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    hit1 = hitk = 0
    reciprocal_rank = 0.0

    for item in data:
        rows = retrieval_service.search(
            item["question"],
            top_k=top_k,
            mode=mode,
            knowledge_base_ids=[item["knowledge_base_id"]],
        )
        names = [str(row.get("file_name", "")) for row in rows]
        rank = next(
            (
                index + 1
                for index, name in enumerate(names)
                if name == item["expected_file"]
            ),
            None,
        )
        hit1 += int(rank == 1)
        if rank is not None and rank <= top_k:
            hitk += 1
            reciprocal_rank += 1 / rank

    total = len(data)
    return {
        "mode": mode,
        "questions": total,
        "hit@1": round(hit1 / total, 4),
        f"hit@{top_k}": round(hitk / total, 4),
        "mrr": round(reciprocal_rank / total, 4),
    }


if __name__ == "__main__":
    print(json.dumps([evaluate("vector"), evaluate("hybrid")], ensure_ascii=False, indent=2))
