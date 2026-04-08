from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class ToolResult:
    success: bool
    result: Any
    error: Optional[str] = None


class ToolExecutor:
    """
    工具执行器：执行各类工具调用（Core Memory 操作、LLM 查询等）。
    提供统一的任务执行接口。
    """

    def __init__(self, core_memory_cache=None, llm=None, event_bus=None):
        self.core_memory_cache = core_memory_cache
        self.llm = llm
        self.event_bus = event_bus

    async def run(self, tool_spec: dict) -> dict:
        """
        执行工具调用。

        tool_spec 格式：
        {
            "name": "tool_name",
            "args": {...},  // 工具参数
        }
        """
        tool_name = tool_spec.get("name", "")
        tool_args = tool_spec.get("args", {})

        match tool_name:
            case "read_core_memory":
                return await self._read_core_memory(tool_args)
            case "update_core_memory":
                return await self._update_core_memory(tool_args)
            case "query_vector":
                return await self._query_vector(tool_args)
            case "write_graph":
                return await self._write_graph(tool_args)
            case "llm_generate":
                return await self._llm_generate(tool_args)
            case "get_evolution_summary":
                return await self._get_evolution_summary(tool_args)
            case "record_preference":
                return await self._record_preference(tool_args)
            case _:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                }

    async def _read_core_memory(self, args: dict) -> dict:
        user_id = args.get("user_id", "default")
        block = args.get("block", None)

        try:
            memory = self.core_memory_cache.get(user_id)
            if block:
                if hasattr(memory, block):
                    return {
                        "success": True,
                        "result": getattr(memory, block).model_dump(),
                    }
                return {"success": False, "error": f"Unknown block: {block}"}
            return {
                "success": True,
                "result": memory.model_dump(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _update_core_memory(self, args: dict) -> dict:
        user_id = args.get("user_id", "default")
        block = args.get("block", "")
        data = args.get("data", {})

        try:
            memory = self.core_memory_cache.get(user_id)
            if not hasattr(memory, block):
                return {"success": False, "error": f"Unknown block: {block}"}

            block_obj = getattr(memory, block)
            for key, value in data.items():
                if hasattr(block_obj, key):
                    setattr(block_obj, key, value)

            self.core_memory_cache.set(user_id, memory)
            return {
                "success": True,
                "result": {"updated_block": block},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _query_vector(self, args: dict) -> dict:
        query = args.get("query", "")
        user_id = args.get("user_id", "default")
        top_k = args.get("top_k", 5)

        try:
            if not hasattr(self, "vector_retriever") or not self.vector_retriever:
                return {"success": False, "error": "Vector retriever not configured"}

            result = await self.vector_retriever.search(query, user_id, top_k=top_k)
            return {
                "success": True,
                "result": {"context": result},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _write_graph(self, args: dict) -> dict:
        subject = args.get("subject", "")
        relation = args.get("relation", "")
        obj = args.get("object", "")
        confidence = args.get("confidence", 0.5)

        try:
            if not hasattr(self, "graph_db") or not self.graph_db:
                return {"success": False, "error": "Graph DB not configured"}

            await self.graph_db.upsert_relation(
                subject=subject,
                relation=relation,
                object=obj,
                confidence=confidence,
            )
            return {
                "success": True,
                "result": {"subject": subject, "relation": relation, "object": obj},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _llm_generate(self, args: dict) -> dict:
        prompt = args.get("prompt", "")

        try:
            if not self.llm:
                return {"success": False, "error": "LLM not configured"}

            response = await self.llm.generate(prompt)
            return {
                "success": True,
                "result": {"response": response},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _get_evolution_summary(self, args: dict) -> dict:
        last_n = args.get("last_n", 20)

        try:
            if not hasattr(self, "evolution_journal") or not self.evolution_journal:
                return {"success": False, "error": "Evolution journal not configured"}

            summary = await self.evolution_journal.get_growth_summary(last_n)
            return {
                "success": True,
                "result": {"summary": summary},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _record_preference(self, args: dict) -> dict:
        user_id = args.get("user_id", "default")
        preference_type = args.get("type", "PREFERS")
        item = args.get("item", "")
        confidence = args.get("confidence", 0.8)

        try:
            if not hasattr(self, "graph_db") or not self.graph_db:
                return {"success": False, "error": "Graph DB not configured"}

            await self.graph_db.upsert_relation(
                subject=user_id,
                relation=preference_type,
                object=item,
                confidence=confidence,
            )
            return {
                "success": True,
                "result": {
                    "user_id": user_id,
                    "preference": f"{preference_type} {item}",
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
