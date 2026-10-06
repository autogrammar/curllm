"""Documented v2 entrypoint backed by the shared LLM-DSL plan engine."""

from curllm_core.llm_dsl.executor import DSLExecutor, ExecutionResult


LLMExecutionResult = ExecutionResult


class LLMDSLExecutor(DSLExecutor):
    """Execute natural-language instructions through generated atomic queries."""

    async def execute(self, instruction: str) -> LLMExecutionResult:
        return await self.execute_natural_language(instruction)
