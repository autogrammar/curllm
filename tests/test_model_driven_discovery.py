import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from curllm_core.orchestrator_steps import StepExecutor
from curllm_core.task_planner import TaskStep, StepType
from curllm_core.command_parser import ParsedCommand
from curllm_core.atomic_functions import AtomicFunctionExecutor


class DummyElement:
    def __init__(self, tag="input", visible=True, text=""):
        self._tag = tag
        self._visible = visible
        self._text = text
        self.clicked = False
        self.filled_text = ""
        self.typed_text = ""

    async def is_visible(self):
        return self._visible

    async def scroll_into_view_if_needed(self):
        pass

    async def click(self, **kwargs):
        self.clicked = True

    async def fill(self, val):
        self.filled_text = val

    async def type(self, text, delay=0):
        self.typed_text = text

    async def inner_text(self):
        return self._text


class DummyKeyboard:
    def __init__(self):
        self.pressed = []

    async def press(self, key):
        self.pressed.append(key)


class DummyPage:
    def __init__(self):
        self.url = "https://example.com"
        self.keyboard = DummyKeyboard()
        self.elements = {}
        self.eval_results = {}

    async def query_selector(self, selector):
        return self.elements.get(selector)

    async def query_selector_all(self, selector):
        el = self.elements.get(selector)
        return [el] if el else []

    async def evaluate(self, script, *args):
        for k, v in self.eval_results.items():
            if k in str(script):
                if callable(v):
                    return v(*args)
                return v
        return []

    async def wait_for_load_state(self, state, timeout=0):
        pass


@pytest.mark.asyncio
async def test_step_executor_search_standard():
    page = DummyPage()
    search_input = DummyElement()
    page.elements["#search-box"] = search_input

    finder = MagicMock()
    match = MagicMock()
    match.selector = "#search-box"
    match.confidence = 0.95
    finder.find_search_input = AsyncMock(return_value=match)

    executor = StepExecutor(page=page, resolver=None, element_finder=finder)
    step = TaskStep(step_type=StepType.SEARCH, description="Search", params={"query": "laptop"})
    parsed = ParsedCommand(original_instruction="search laptop")

    result = await executor.execute(step, parsed)
    assert result["filled"] is True
    assert result["query"] == "laptop"
    assert search_input.typed_text == "laptop"
    assert "Enter" in page.keyboard.pressed


@pytest.mark.asyncio
async def test_step_executor_search_llm_fallback():
    page = DummyPage()
    search_input = DummyElement()
    page.elements["#discovered-search"] = search_input

    # Standard element finder fails
    finder = MagicMock()
    finder.find_search_input = AsyncMock(return_value=None)

    # Page evaluate returns candidate inputs
    page.eval_results["querySelectorAll('input, textarea"] = [
        {"selector": "#discovered-search", "type": "text", "placeholder": "Search catalog...", "name": "q"}
    ]

    llm = MagicMock()
    llm.aquery = AsyncMock(return_value='{"selector": "#discovered-search"}')

    executor = StepExecutor(page=page, resolver=None, element_finder=finder, llm=llm)
    step = TaskStep(step_type=StepType.SEARCH, description="Search", params={"query": "tablet"})
    parsed = ParsedCommand(original_instruction="search tablet")

    result = await executor.execute(step, parsed)
    assert result["filled"] is True
    assert result["selector"] == "#discovered-search"
    assert search_input.typed_text == "tablet"


@pytest.mark.asyncio
async def test_atomic_functions_find_containers_with_llm():
    page = DummyPage()
    card_el = DummyElement(text="Company ACME Inc. Warsaw")
    page.elements["div.company-card"] = card_el

    llm = MagicMock()
    llm.generate = AsyncMock(return_value='["div.company-card", ".item-box"]')

    executor = AtomicFunctionExecutor(page=page, llm=llm)
    containers = await executor.find_containers(entity_type="company")

    assert len(containers) >= 1
    assert containers[0]["selector"] == "div.company-card"
    assert "Company ACME" in containers[0]["preview_text"]


@pytest.mark.asyncio
async def test_atomic_functions_find_containers_semantic_fallback():
    page = DummyPage()
    card_el = DummyElement(text="Product A 120 PLN")
    page.elements["article.product-card"] = card_el

    # No LLM, fallback discovery
    page.eval_results["querySelectorAll"] = [
        {"selector": "article.product-card", "preview": "Product A 120 PLN", "tag": "article", "className": "product-card"}
    ]

    executor = AtomicFunctionExecutor(page=page, llm=None)
    containers = await executor.find_containers(entity_type="product")

    assert len(containers) >= 1
    assert containers[0]["selector"] == "article.product-card"
