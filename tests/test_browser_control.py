"""Browser identity and truthful plan outcome regressions; no LLM/network calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright

from curllm_core.llm_dsl.atoms import AtomicFunctions, AtomResult
from curllm_core.llm_dsl.executor import DSLExecutor
from curllm_core.llm_dsl.generator import DSLPlan, DSLQuery


@pytest.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            page.set_default_timeout(2000)
            yield page
        finally:
            await browser.close()


@pytest.mark.parametrize("editor", [
    '<textarea id="editor" aria-label="chat">draft</textarea>',
    '<div id="editor" contenteditable="true" aria-label="chat">draft</div>',
    '<div id="editor" contenteditable="plaintext-only" aria-label="chat">draft</div>',
])
async def test_matching_focused_editor_is_detected_and_filled(page, editor):
    await page.set_content('<textarea id="other" aria-label="chat">keep</textarea>' + editor)
    await page.locator("#editor").focus()
    result = await AtomicFunctions(page).find_input_by_context("chat")
    assert result.success
    control = page.locator(result.data["selector"])
    assert await control.count() == 1
    assert await control.get_attribute("id") == "editor"
    assert "draft" not in str(result.data)
    await control.fill("Gdynia")
    assert await page.locator("#other").input_value() == "keep"
    assert await control.evaluate("el => el.value ?? el.textContent") == "Gdynia"
    assert await page.evaluate("document.activeElement.id") == "editor"


@pytest.mark.parametrize("unavailable", [
    '<input aria-label="chat" disabled>',
    '<fieldset disabled><input aria-label="chat"></fieldset>',
    '<textarea aria-label="chat" readonly></textarea>',
    '<input aria-label="chat" type="hidden">',
    '<input aria-label="chat" style="visibility:hidden">',
    '<input aria-label="chat" style="display:none">',
    '<div inert><input aria-label="chat"></div>',
    '<div aria-disabled="true"><div contenteditable="true" aria-label="chat"></div></div>',
    '<div aria-hidden="true"><input aria-label="chat"></div>',
    '<div contenteditable="false" aria-label="chat">locked</div>',
])
async def test_unavailable_controls_are_not_offered(page, unavailable):
    await page.set_content(unavailable)
    assert not (await AtomicFunctions(page).find_input_by_context("chat")).success


@pytest.mark.parametrize("markup", [
    '<input aria-label="else"><section><textarea aria-label="chat"></textarea></section>',
    '<div><textarea name="shared" aria-label="else"></textarea></div>'
    '<section><textarea name="shared" aria-label="chat"></textarea></section>',
    '<textarea id="chat:editor.with space" aria-label="chat"></textarea>',
    '<textarea id="duplicate" aria-label="else"></textarea>'
    '<textarea id="duplicate" aria-label="chat"></textarea>',
    '<input name="a&quot;b" aria-label="chat">',
    '<input style="position:fixed;top:0" aria-label="chat">',
])
async def test_selector_identifies_one_control_in_the_actual_dom(page, markup):
    await page.set_content(markup)
    result = await AtomicFunctions(page).find_input_by_context("chat")
    assert result.success
    locator = page.locator(result.data["selector"])
    assert await locator.count() == 1
    assert await locator.get_attribute("aria-label") == "chat"
    await locator.fill("verified")
    assert await locator.input_value() == "verified"


async def test_llm_index_addresses_the_filtered_candidate_list(page):
    await page.set_content('<input disabled><textarea aria-label="chat"></textarea>')
    llm = SimpleNamespace(agenerate=AsyncMock(return_value=SimpleNamespace(
        generations=[[SimpleNamespace(text="0")]])))
    result = await AtomicFunctions(page, llm).find_input_by_context("chat")
    assert result.success
    assert await page.locator(result.data["selector"]).get_attribute("aria-label") == "chat"


async def test_unrelated_focus_does_not_override_requested_purpose(page):
    await page.set_content('<section><input id="search" aria-label="search"></section>'
                           '<section><textarea id="chat" aria-label="chat"></textarea></section>')
    await page.locator("#search").focus()
    result = await AtomicFunctions(page).find_input_by_context("chat")
    assert result.success
    assert await page.locator(result.data["selector"]).get_attribute("id") == "chat"
    assert await page.evaluate("document.activeElement.id") == "search"


async def test_plan_partial_failure_is_not_success():
    executor = DSLExecutor()
    executor.execute_query = AsyncMock(side_effect=[AtomResult(True, {"field": "found"}), AtomResult(False)])
    executor.generator.refine_query = AsyncMock(return_value=None)
    result = await executor.execute_plan(DSLPlan([
        DSLQuery("find_input_by_context", {}), DSLQuery("find_clickable_by_intent", {})
    ], "find a field and a submit control", 1.0))
    assert not result.success
    assert result.errors == ["find_clickable_by_intent: No result"]
    assert result.results["q0_find_input_by_context"].success


async def test_retry_recovery_removes_the_recovered_error():
    executor = DSLExecutor()
    query = DSLQuery("find_input_by_context", {})
    executor.execute_query = AsyncMock(side_effect=[AtomResult(False), AtomResult(True, {"selector": "#chat"})])
    executor.generator.refine_query = AsyncMock(return_value=query)
    result = await executor.execute_plan(DSLPlan([query], "find chat", 1.0))
    assert result.success
    assert result.errors == []
    assert result.final_data == {"selector": "#chat"}


async def test_failed_retry_has_one_final_error():
    executor = DSLExecutor()
    query = DSLQuery("find_input_by_context", {})
    executor.execute_query = AsyncMock(side_effect=[AtomResult(False), RuntimeError("retry failed")])
    executor.generator.refine_query = AsyncMock(return_value=query)
    result = await executor.execute_plan(DSLPlan([query], "find chat", 1.0))
    assert not result.success
    assert result.errors == ["find_input_by_context: retry failed"]


async def test_empty_plan_is_not_success():
    assert not (await DSLExecutor().execute_plan(DSLPlan([], "nothing", 1.0))).success
