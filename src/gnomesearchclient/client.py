__all__ = ["Result", "Client", "ClientStateful"]

import os
import sys

import asyncio
import configparser
import dbus_next.auth
from dbus_next.aio import MessageBus

from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional, Iterable

import logging
logger = logging.getLogger(__name__)

from .provider import Provider


@dataclass(frozen=True)
class Result[T]:
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
    def __init__(self, auth: dbus_next.auth.Authenticator = None):
        self.bus = MessageBus(auth=auth)
        self.connected = False
        self.search_providers: set[Provider] = set()

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
                    self.search_providers.add(search_provider)

                except (KeyError, configparser.Error, OSError) as e:
                    print(f"Skipping invalid provider {ini_path}: {e}", file=sys.stderr)

    async def connect(self):
        await self.bus.connect()

    async def disconnect(self):
        self.bus.disconnect()

    @staticmethod
    async def _get_initial_result_sets(search_providers: Iterable[Provider], search_terms: list[str],
                                       timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """Query all the search providers for the same query. Yield results as they arrive"""
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

    def get_initial_result_sets(self, search_terms: list[str], timeout: float = 30) -> AsyncGenerator[
        Result[list[str]], None]:
        """Query all the search providers for the same query. Yield results as they arrive"""
        return self._get_initial_result_sets(self.search_providers, search_terms, timeout)

    async def get_subsearch_result_sets(self, previous_search_results: list[Result[list[str]]],
                                        current_search_terms: list[str],
                                        additional_providers=None, timeout: float = 30) -> AsyncGenerator[
        Result[list[str]], None]:
        """
        Refine the initial search after the user types in more characters in the search entry.
        Also gets the initial result sets for any providers specified if there are providers that did not finish their
        previous search.

        :param previous_search_results: List of the previous search results returned from the ``get_initial_result_set()`` function.
        :param current_search_terms: Updated search terms.
        :param additional_providers:
        :param timeout:
        :return: List of updated search results.
        """
        # I don't know what the best way to handle this would be. It would be nice if this function was stateful and
        # would automatically use the previous search. Maybe I'll make a wrapper around this that keeps state information

        tasks: dict[asyncio.Task, Provider] = {}

        other_failed_providers = []

        try:
            for result in previous_search_results:
                if result.results:
                    task = asyncio.create_task(
                        asyncio.wait_for(
                            result.search_provider.get_subsearch_result_set(result.results, current_search_terms),
                            timeout=timeout)
                    )
                    tasks[task] = result.search_provider
                else:
                    other_failed_providers.append(result.search_provider)

            if additional_providers is not None:
                for provider in additional_providers:
                    task = asyncio.create_task(
                        asyncio.wait_for(provider.get_initial_result_set(current_search_terms), timeout=timeout)
                    )
                    tasks[task] = provider

            for provider in other_failed_providers:
                task = asyncio.create_task(
                    asyncio.wait_for(provider.get_initial_result_set(current_search_terms), timeout=timeout)
                )
                tasks[task] = provider

            async for coroutine in asyncio.as_completed(tasks.keys()):
                search_provider = tasks[coroutine]
                try:
                    result = await coroutine
                    yield Result(search_provider, current_search_terms, result)
                except Exception as ex:
                    yield Result(search_provider, current_search_terms, error=ex)
        finally:
            for task in tasks.keys():
                if not task.done():
                    print(f"Cancelling {tasks[task].provider_info.bus_name}")
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass


class ClientStateful(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.previous_search_results: list[Result[list[str]]] = []
        self.previous_search_providers_that_did_not_finish: set[Provider] = set()

    async def get_initial_result_sets(self, search_terms: list[str], timeout: float = 30) -> AsyncGenerator[
        Result[list[str]], None]:
        """TODO"""
        self.previous_search_results.clear()
        self.previous_search_providers_that_did_not_finish.update(self.search_providers)
        gen = super().get_initial_result_sets(search_terms, timeout)
        async for result in gen:
            self.previous_search_results.append(result)
            self.previous_search_providers_that_did_not_finish.discard(result.search_provider)
            yield result

    async def get_subsearch_result_sets(self, current_search_terms: list[str], timeout: float = 30) -> AsyncGenerator[
        Result[list[str]], None]:
        """
        Refine the initial search after the user types in more characters in the search entry.
        If the provider did not complete the first search it is restarted.

        :param current_search_terms: Updated search terms.
        :param timeout:
        :return: List of updated search results.
        """
        gen = super().get_subsearch_result_sets(self.previous_search_results, current_search_terms,
                                                self.previous_search_providers_that_did_not_finish, timeout=timeout)
        self.previous_search_providers_that_did_not_finish.clear()
        self.previous_search_providers_that_did_not_finish.update(self.search_providers)
        self.previous_search_results.clear()
        async for result in gen:
            self.previous_search_results.append(result)
            self.previous_search_providers_that_did_not_finish.discard(result.search_provider)
            yield result
