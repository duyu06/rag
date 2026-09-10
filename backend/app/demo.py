from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.ingestion import document_path, ingest_file
from app.knowledge import get_base
from app.store import vector_store

DEMO_MANIFEST = [
    {"file_name": "01-差旅费用管理制度.md", "knowledge_base_id": "kb_public"},
    {"file_name": "06-信息安全管理规范.md", "knowledge_base_id": "kb_public"},
    {"file_name": "07-会议与接待管理制度.md", "knowledge_base_id": "kb_public"},
    {"file_name": "08-办公用品采购规范.md", "knowledge_base_id": "kb_public"},
    {"file_name": "05-HR员工手册.md", "knowledge_base_id": "kb_hr"},
    {"file_name": "09-考勤与加班管理办法.md", "knowledge_base_id": "kb_hr"},
    {"file_name": "10-休假与请假制度.md", "knowledge_base_id": "kb_hr"},
    {"file_name": "11-绩效与调薪管理制度.md", "knowledge_base_id": "kb_hr"},
    {"file_name": "03-X100产品说明书.md", "knowledge_base_id": "kb_product"},
    {"file_name": "12-X200产品说明书.md", "knowledge_base_id": "kb_product"},
    {"file_name": "13-产品常见问题FAQ.md", "knowledge_base_id": "kb_product"},
    {"file_name": "14-设备安装与部署指南.md", "knowledge_base_id": "kb_product"},
    {"file_name": "04-销售折扣管理办法.md", "knowledge_base_id": "kb_sales"},
    {"file_name": "15-客户分级管理办法.md", "knowledge_base_id": "kb_sales"},
    {"file_name": "16-销售报价流程.md", "knowledge_base_id": "kb_sales"},
    {"file_name": "17-合同审批规范.md", "knowledge_base_id": "kb_sales"},
    {"file_name": "02-售后退款SOP.md", "knowledge_base_id": "kb_service"},
    {"file_name": "18-退换货处理规范.md", "knowledge_base_id": "kb_service"},
    {"file_name": "19-客户投诉处理SOP.md", "knowledge_base_id": "kb_service"},
    {"file_name": "20-质保与维修政策.md", "knowledge_base_id": "kb_service"},
]


def _source_dir() -> Path:
    path = Path(settings.demo_data_dir).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Demo 数据目录不存在：{path}")
    return path


def _chunk_inventory() -> dict[tuple[str, str], dict[str, object]]:
    rows = vector_store.all_chunks()
    inventory: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row.get("knowledge_base_id", "")), str(row.get("file_name", "")))
        if not all(key):
            continue
        item = inventory.setdefault(key, {"count": 0, "versions": set()})
        item["count"] = int(item["count"]) + 1
        versions = item["versions"]
        if isinstance(versions, set):
            versions.add(str(row.get("retrieval_schema_version") or "legacy"))
    return inventory


def _is_current_index(item: dict[str, object] | None) -> bool:
    if not item or int(item.get("count", 0) or 0) <= 0:
        return False
    versions = item.get("versions")
    return isinstance(versions, set) and versions == {settings.retrieval_schema_version}


def demo_status() -> dict:
    inventory = _chunk_inventory()
    items = []
    ready_count = 0
    for item in DEMO_MANIFEST:
        kb_id = item["knowledge_base_id"]
        file_name = item["file_name"]
        state = inventory.get((kb_id, file_name))
        chunks = int((state or {}).get("count", 0) or 0)
        index_current = _is_current_index(state)
        ready = document_path(kb_id, file_name).exists() and chunks > 0 and index_current
        if ready:
            ready_count += 1
        items.append(
            {
                **item,
                "knowledge_base_name": get_base(kb_id)["name"],
                "ready": ready,
                "chunk_count": chunks,
                "index_current": index_current,
            }
        )
    return {
        "ready": ready_count == len(DEMO_MANIFEST),
        "ready_count": ready_count,
        "total": len(DEMO_MANIFEST),
        "retrieval_schema_version": settings.retrieval_schema_version,
        "items": items,
    }


def initialize_demo(force: bool = False) -> dict:
    source_dir = _source_dir()
    inventory = _chunk_inventory()
    results = []

    for item in DEMO_MANIFEST:
        kb_id = item["knowledge_base_id"]
        file_name = item["file_name"]
        source = source_dir / file_name
        if not source.exists():
            raise FileNotFoundError(f"缺少 Demo 文件：{source}")

        target = document_path(kb_id, file_name)
        source_bytes = source.read_bytes()
        state = inventory.get((kb_id, file_name))
        chunks = int((state or {}).get("count", 0) or 0)
        unchanged = (
            target.exists()
            and target.read_bytes() == source_bytes
            and chunks > 0
            and _is_current_index(state)
        )

        if unchanged and not force:
            results.append(
                {
                    **item,
                    "knowledge_base_name": get_base(kb_id)["name"],
                    "status": "skipped",
                    "chunks_stored": chunks,
                }
            )
            continue

        target.write_bytes(source_bytes)
        chunk_count = ingest_file(target, kb_id)
        results.append(
            {
                **item,
                "knowledge_base_name": get_base(kb_id)["name"],
                "status": "indexed",
                "chunks_stored": chunk_count,
            }
        )

    return {
        "success": True,
        "message": "Demo 数据已初始化",
        "results": results,
        "status": demo_status(),
    }


def reset_demo() -> dict:
    """Reset only bundled demo documents; user-uploaded documents are preserved."""
    for item in DEMO_MANIFEST:
        kb_id = item["knowledge_base_id"]
        file_name = item["file_name"]
        vector_store.delete_file(file_name, kb_id)
        document_path(kb_id, file_name).unlink(missing_ok=True)
    result = initialize_demo(force=True)
    result["message"] = "Demo 数据已重置并重新索引"
    return result
