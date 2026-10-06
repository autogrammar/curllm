"""Documented v2 execution and real MCP stdio transport regressions."""

import asyncio
import logging
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("succeeded", [True, False])
async def test_v2_execute_uses_the_existing_plan_engine(succeeded):
    from curllm_core.llm_dsl.atoms import AtomResult
    from curllm_core.llm_dsl.generator import DSLPlan, DSLQuery
    from curllm_core.v2 import LLMDSLExecutor, LLMExecutionResult

    executor = LLMDSLExecutor()
    executor.generator.generate_plan = AsyncMock(return_value=DSLPlan(
        [DSLQuery("find_input_by_context", {"purpose_description": "chat"})], "find chat", 1.0))
    executor.generator.refine_query = AsyncMock(return_value=None)
    executor.atoms.find_input_by_context = AsyncMock(return_value=AtomResult(
        succeeded, {"selector": "#chat"} if succeeded else None))

    result = await executor.execute("find chat")

    assert isinstance(result, LLMExecutionResult)
    assert result.success is succeeded
    executor.generator.generate_plan.assert_awaited_once_with("find chat", None)
    executor.atoms.find_input_by_context.assert_awaited_once_with(purpose_description="chat")


async def test_mcp_stdio_has_no_non_json_log_messages(caplog, tmp_path):
    # The product declares MCP >=1,<2. Global SDK 2.x installations use a different API.
    pytest.importorskip("mcp.server.fastmcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["CURLLM_SCREENSHOT_DIR"] = str(tmp_path / "screenshots")
    env["CURLLM_MCP_ALLOW_EXECUTE"] = "0"
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "curllm_mcp.server"],
        cwd=str(Path(__file__).resolve().parents[1]), env=env)

    async def exercise_protocol():
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "curllm_interfaces" in {tool.name for tool in tools.tools}
                response = await session.call_tool("curllm_interfaces", {})
                assert not response.isError

    with caplog.at_level(logging.ERROR, logger="mcp.client.stdio"):
        await asyncio.wait_for(exercise_protocol(), timeout=45)
    assert not [record for record in caplog.records
                if "Failed to parse JSONRPC message from server" in record.getMessage()]
