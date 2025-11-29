__all__ = ["Result", "Client", "ClientStateful"]

import os
import sys

import asyncio
import configparser
import dbus_next.auth
from dbus_next.aio import MessageBus

from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional, Iterable, Generic, TypeVar
T = TypeVar("T")

import logging
logger = logging.getLogger(__name__)

from .provider import Provider


@dataclass(frozen=True)
class Result(Generic[T]):
    search_provider: Provider
    query: list[str]
    results: Optional[T] = None
    error: Optional[Exception] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.results is not None

    def __repr__(self) -> str:
        if self.succeeded:
            return f"{self.search_provider.desktop_id}: {len(self.results)} results"
        else:
            err_name = type(self.error).__name__ if self.error else "Unknown"
            return f"{self.search_provider.desktop_id}: {err_name}"


class Client:
    """Class for interacting with the Gnome search providers."""
    def __init__(self, auth: dbus_next.auth.Authenticator = None):
        self.bus = MessageBus(auth=auth)
        self.connected = False
        self.providers: set[Provider] = set()

    async def init(self):
        await self.connect()
        await self._collect_search_providers()

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()

    @staticmethod
    def _get_search_provider_dirs() -> list[Path]:
        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        paths = [Path(p) / "gnome-shell" / "search-providers" for p in xdg_data_dirs.split(":")]
        # Add Flatpak user/system exports as fallback
        # paths += [
        #     Path("~/.local/share/flatpak/exports/share/gnome-shell/search-providers").expanduser(),
        #     Path("/var/lib/flatpak/exports/share/gnome-shell/search-providers"),
        # ]
        return paths

    async def _collect_search_providers(self):
        # Assume the search providers exist in the folder Gnome expects. A different implementation exists
        # that instead loops through every single name and every single path to find if any bus
        # implements the SearchProvider2 interface. This would work but would be wildly slow.
        # I _think_ the files should always be there but maybe not idk.
        # Looking at the arch packages website the apps that implement providers always put the file there so maybe

        seen = set()

        for base_dir in self._get_search_provider_dirs():
            if not base_dir.is_dir():
                continue
            for ini_path in base_dir.glob("*.ini"):
                if ini_path in seen:
                    continue
                seen.add(ini_path)

                try:
                    config = configparser.ConfigParser()
                    config.read(ini_path)
                    section = config["Shell Search Provider"]
                    desktop_id = section["DesktopID"]
                    bus_name = section["BusName"]
                    object_path = section["ObjectPath"]

                    search_provider = Provider(desktop_id, bus_name, object_path, self.bus)
                    await search_provider.init()
                    self.providers.add(search_provider)

                except (KeyError, configparser.Error, OSError) as e:
                    logger.warning(f"Skipping invalid provider {ini_path}: {e}")

    async def connect(self):
        await self.bus.connect()

    async def disconnect(self):
        self.bus.disconnect()

    @staticmethod
    async def _get_initial_result_sets(search_providers: Iterable[Provider], search_terms: list[str],
                                       timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        tasks: dict[asyncio.Task, Provider] = {}

        try:
            for search_provider in search_providers:
                task = asyncio.create_task(
                    search_provider.get_initial_result_set(search_terms)
                )
                tasks[task] = search_provider

            async with asyncio.timeout(timeout):
                async for coroutine in asyncio.as_completed(tasks.keys()):
                    search_provider = tasks[coroutine]
                    try:
                        result = await coroutine
                        yield Result(search_provider, search_terms, result)
                    except Exception as ex:
                        yield Result(search_provider, search_terms, error=ex)

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

    def get_initial_result_sets(self, search_terms: list[str], timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """
        Query the search providers for a search term.

        Functions as an async generator that yields results as the providers finish generating them.
        Should cancel any incomplete searches if the loop exits early or is manually cancelled.

        :param search_terms: List of search terms.
        :param timeout: Time to wait for provider before cancelling search.
        :return: AsyncGenerator of results.
        """
        return self._get_initial_result_sets(self.providers, search_terms, timeout)

    @staticmethod
    async def get_subsearch_result_sets(
                previous_search_results: Iterable[Result[list[str]]],
                current_search_terms: list[str],
                additional_providers: Iterable[Provider]=None, timeout: float = 30
            ) -> AsyncGenerator[Result[list[str]], None]:
        """
        Refine the initial search after the user types in more characters in the search entry.

        :param previous_search_results: List of the previous search results.
        :param current_search_terms: Updated search terms.
        :param additional_providers: Any additional providers to manually get the initial results for.
        :param timeout: Time to wait for provider before cancelling search.
        :return: AsyncGenerator of updated results.
        """
        tasks: dict[asyncio.Task, Provider] = {}

        other_failed_providers = []

        try:
            # Providers that did finish their previous search should receive their previous search results as input
            # so that it can be refined
            for result in previous_search_results:
                if result.results:
                    task = asyncio.create_task(
                        result.search_provider.get_subsearch_result_set(result.results, current_search_terms)
                    )
                    tasks[task] = result.search_provider
                else:
                    other_failed_providers.append(result.search_provider)

            # Mostly used for restarting providers that didn't finish their previous search by the stateful class.
            if additional_providers is not None:
                for provider in additional_providers:
                    task = asyncio.create_task(
                        provider.get_initial_result_set(current_search_terms)
                    )
                    tasks[task] = provider

            # If the previous search returned no results for this provider then just do from the initial
            for provider in other_failed_providers:
                task = asyncio.create_task(
                    provider.get_initial_result_set(current_search_terms)
                )
                tasks[task] = provider

            async with asyncio.timeout(timeout):
                async for coroutine in asyncio.as_completed(tasks.keys()):
                    search_provider = tasks[coroutine]
                    try:
                        result = await coroutine
                        yield Result(search_provider, current_search_terms, result)
                    except Exception as ex:
                        yield Result(search_provider, current_search_terms, error=ex)
        finally:
            # If the generator exits early or any exception is raised cleanup by cancelling all remaining tasks
            for task in tasks.keys():
                if not task.done():
                    logger.debug(f"Cancelling {tasks[task].provider_info.bus_name}")
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass


class ClientStateful:
    """Wraps the Client class and maintains state information between get results calls."""
    def __init__(self, client: Client):
        self.client = client
        self.previous_results: list[Result[list[str]]] = []
        self.unfinished_providers: set[Provider] = set()

    async def init(self):
        await self.client.init()

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

    @property
    def providers(self) -> set[Provider]:
        return self.client.providers

    async def get_initial_result_sets(self, search_terms: list[str], timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """
        Query the search providers for a search term.

        Functions as an async generator that yields results as the providers finish generating them.
        Should cancel any incomplete searches if the loop exits early or is manually cancelled.

        :param search_terms: List of search terms.
        :param timeout: Time to wait for provider before cancelling search.
        :return: AsyncGenerator of results.
        """
        self.previous_results.clear()
        self.unfinished_providers.update(self.client.providers)
        async for result in self.client.get_initial_result_sets(search_terms, timeout):
            self.previous_results.append(result)
            self.unfinished_providers.discard(result.search_provider)
            yield result

    async def get_subsearch_result_sets(self, current_search_terms: list[str], timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """
        Refine the initial search after the user types in more characters in the search entry.
        If the provider did not complete the first search it is restarted.
        Uses state information from previous searches to update the results.

        :param current_search_terms: Updated search terms.
        :param timeout: Time to wait for provider before cancelling search.
        :return: List of updated search results.
        """
        # Start the search with the state information
        gen = self.client.get_subsearch_result_sets(self.previous_results, current_search_terms,
                                                    self.unfinished_providers, timeout=timeout)
        # Then set the unfinished providers to all of them and clear them out as results arrive
        self.unfinished_providers.clear()
        self.unfinished_providers.update(self.client.providers)
        self.previous_results.clear()
        async for result in gen:
            self.previous_results.append(result)
            self.unfinished_providers.discard(result.search_provider)
            yield result

    def clear_previous_results(self) -> None:
        """Clears the state information."""
        self.previous_results.clear()

    def get_search_result_sets(self, search_terms: list[str], timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """
        Alias for the `get_subsearch_result_sets` function.

        Using this and the `clear_previous_results` function the same functionality can be accomplished as using
        the get_initial and get_subsearch functions but without maintaining which function to use at which time.

        For example, the clear function could be called when beginning a new session and then this function used
        exclusively for all subsequent searches.

        :param search_terms: List of search terms.
        :param timeout: Time to wait for provider before cancelling search.
        """
        return self.get_subsearch_result_sets(search_terms, timeout)
