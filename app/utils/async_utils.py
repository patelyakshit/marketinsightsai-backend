"""
Async utilities for safe task handling.

asyncio.create_task() can silently swallow exceptions if not handled properly.
These utilities ensure proper error logging and optional callbacks.
"""

import asyncio
import logging
from typing import Callable, Coroutine, Any, Optional

logger = logging.getLogger(__name__)


def _handle_task_exception(task: asyncio.Task, task_name: str = "background_task") -> None:
    """
    Callback for handling exceptions in background tasks.

    This prevents silent failures by logging any exceptions that occur
    in tasks created with asyncio.create_task().
    """
    try:
        # This will raise if the task had an exception
        task.result()
    except asyncio.CancelledError:
        logger.debug(f"Task '{task_name}' was cancelled")
    except Exception as e:
        logger.error(f"Exception in background task '{task_name}': {e}", exc_info=True)


def create_task_with_error_handling(
    coro: Coroutine[Any, Any, Any],
    task_name: str = "background_task",
    on_error: Optional[Callable[[Exception], None]] = None,
) -> asyncio.Task:
    """
    Create an asyncio task with proper error handling.

    Unlike bare asyncio.create_task(), this ensures exceptions are logged
    and optionally handled via a callback.

    Args:
        coro: The coroutine to run as a task
        task_name: Name for logging purposes
        on_error: Optional callback for custom error handling

    Returns:
        The created asyncio.Task

    Example:
        ```python
        from app.utils.async_utils import create_task_with_error_handling

        async def my_background_work():
            # Do something that might fail
            pass

        create_task_with_error_handling(
            my_background_work(),
            task_name="my_background_work"
        )
        ```
    """
    task = asyncio.create_task(coro)

    def callback(t: asyncio.Task) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            logger.debug(f"Task '{task_name}' was cancelled")
        except Exception as e:
            logger.error(f"Exception in task '{task_name}': {e}", exc_info=True)
            if on_error:
                try:
                    on_error(e)
                except Exception as callback_error:
                    logger.error(f"Error in on_error callback for '{task_name}': {callback_error}")

    task.add_done_callback(callback)
    return task


async def run_with_timeout(
    coro: Coroutine[Any, Any, Any],
    timeout: float,
    task_name: str = "timed_task",
) -> Any:
    """
    Run a coroutine with a timeout.

    Args:
        coro: The coroutine to run
        timeout: Timeout in seconds
        task_name: Name for logging

    Returns:
        The result of the coroutine

    Raises:
        asyncio.TimeoutError: If the operation times out
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Task '{task_name}' timed out after {timeout}s")
        raise
