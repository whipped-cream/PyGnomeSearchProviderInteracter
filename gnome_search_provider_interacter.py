import asyncio
import os
import sys
from asyncio import Task
from dataclasses import dataclass
from pathlib import Path
import logging
from typing import AsyncGenerator, Optional, Any, Iterable

logger = logging.getLogger(__name__)

import dbus_next.auth
from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.introspection import Node

UNIVERSAL_INTROSPECTION = Node.parse("""\
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
    <interface name="org.gnome.Shell.SearchProvider2">
      <method name="Load" />
        <method name="GetInitialResultSet">
          <arg name="terms" direction="in" type="as" />
            <arg name="result" direction="out" type="as" />
        </method>
        <method name="GetSubsearchResultSet">
          <arg name="previous_results" direction="in" type="as" />
            <arg name="new_terms" direction="in" type="as" />
            <arg name="result" direction="out" type="as" />
        </method>
        <method name="GetResultMetas">
          <arg name="results" direction="in" type="as" />
            <arg name="result" direction="out" type="aa{sv}" />
        </method>
        <method name="ActivateResult">
          <arg name="identifier" direction="in" type="s" />
            <arg name="terms" direction="in" type="as" />
            <arg name="timestamp" direction="in" type="u" />
        </method>
        <method name="LaunchSearch">
          <arg name="terms" direction="in" type="as" />
            <arg name="timestamp" direction="in" type="u" />
        </method>
    </interface>
</node>\
""")

import configparser


@dataclass(frozen=True)
class GnomeSearchProviderInfo:
    desktop_id: str
    bus_name: str
    object_path: str


class GnomeSearchProvider:
    def __init__(self, desktop_id: str, bus_name: str, object_path: str, bus: MessageBus):
        self.provider_info = GnomeSearchProviderInfo(desktop_id, bus_name, object_path)
        self.bus = bus
        self.search_interface = None

    async def init(self) -> None:
        proxy_object = self.bus.get_proxy_object(self.provider_info.bus_name,
                                                 self.provider_info.object_path,
                                                 UNIVERSAL_INTROSPECTION)
        self.search_interface = proxy_object.get_interface("org.gnome.Shell.SearchProvider2")

    def __eq__(self, other):
        return isinstance(other, GnomeSearchProvider) and self.provider_info == other.provider_info

    def __hash__(self):
        return hash(self.provider_info)

    @property
    def bus_name(self) -> str:
        return self.provider_info.bus_name

    @property
    def desktop_id(self) -> str:
        return self.provider_info.desktop_id

    @property
    def object_path(self) -> str:
        return self.provider_info.object_path

    async def get_initial_result_set(self, search_terms: list[str]) -> list[str]:
        """
        Query the search provider for a search term. Return a list of results from the provider.

        The function is used to initiate a search. Results from the initial search can be passed to other functions
        to continue the search with further information.

        :param search_terms: List of search terms. Generally space separated input search.
        :return: List of results.
        """
        return await self.search_interface.call_get_initial_result_set(search_terms)

    async def get_subsearch_result_set(self, previous_search_results: list[str], current_search_terms: list[str]) -> \
    list[str]:
        """
        Refine the initial search after the user types in more characters in the search entry.

        :param previous_search_results: List of the previous search results returned from the ``get_initial_result_set()`` function.
        :param current_search_terms: Updated search terms.
        :return: List of updated search results.
        """
        return await self.search_interface.call_get_subsearch_result_set(previous_search_results, current_search_terms)

    async def get_result_metas(self, result_ids: list[str]) -> list[dict[str, Variant]]:
        """
        Get detailed information about the results.

        The result is a list of dictionaries, one for each input result_id. The dictionaries have the following members:

        - "id": the result ID

        - "name": the display name for the result

        - "icon": a serialized GIcon (see g_icon_serialize()), or alternatively,

        - "gicon": a textual representation of a GIcon (see g_icon_to_string()), or alternatively,

        - "icon-data": a tuple of type (iiibiiay) describing a pixbuf with width, height, rowstride, has-alpha, bits-per-sample, n-channels, and image data

        - "description": an optional short description (1-2 lines)

        - "clipboardText": an optional text to send to the clipboard on activation

        :param result_ids: Result IDs of the previously completed searches.
        :return: List of dictionaries with structure as above.
        """
        return await self.search_interface.call_get_result_metas(result_ids)

    async def activate_result(self, result_id: str, search_terms: list[str], timestamp: int) -> None:
        """
        Activates the result when the search result has been selected to open it in the application.

        :param result_id: Result ID to activate.
        :param search_terms: Search terms.
        :param timestamp: Time the search was executed.
        """
        return await self.search_interface.call_activate_result(result_id, search_terms, timestamp)

    async def launch_search(self, search_terms: list[str], timestamp: int) -> None:
        """
        Display more results in the application.

        :param search_terms: Search terms.
        :param timestamp: Time the search was executed.
        """
        return await self.search_interface.call_launch_search(search_terms, timestamp)


@dataclass(frozen=True)
class Result[T]:
    search_provider: GnomeSearchProvider
    query: list[str]
    results: Optional[T] = None
    error: Optional[Exception] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.results is not None

    def __repr__(self) -> str:
        if self.succeeded:
            return f"✅ {self.search_provider.desktop_id}: {len(self.results)} results"
        else:
            err_name = type(self.error).__name__ if self.error else "Unknown"
            return f"❌ {self.search_provider.desktop_id}: {err_name}"


def _get_search_provider_dirs() -> list[Path]:
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    paths = [Path(p) / "gnome-shell" / "search-providers" for p in xdg_data_dirs.split(":")]
    # Add Flatpak user/system exports as fallback
    # paths += [
    #     Path("~/.local/share/flatpak/exports/share/gnome-shell/search-providers").expanduser(),
    #     Path("/var/lib/flatpak/exports/share/gnome-shell/search-providers"),
    # ]
    return paths


class GnomeSearchProviderInteracter:
    def __init__(self, auth: dbus_next.auth.Authenticator = None):
        self.bus = MessageBus(auth=auth)
        self.connected = False
        self.search_providers: set[GnomeSearchProvider] = set()

    async def init(self):
        await self.connect()
        await self._collect_search_providers()

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()

    async def _collect_search_providers(self):
        # Assume the search providers exist in the folder Gnome expects. A different implementation exists
        # that instead loops through every single name and every single path to find if any bus
        # implements the SearchProvider2 interface. This would work but would be wildly slow.
        # I _think_ the files should always be there but maybe not idk.
        # Looking at the arch packages website the apps that implement providers always put the file there so maybe

        seen = set()

        for base_dir in _get_search_provider_dirs():
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

                    search_provider = GnomeSearchProvider(desktop_id, bus_name, object_path, self.bus)
                    await search_provider.init()
                    self.search_providers.add(search_provider)

                except (KeyError, configparser.Error, OSError) as e:
                    print(f"Skipping invalid provider {ini_path}: {e}", file=sys.stderr)

    async def connect(self):
        await self.bus.connect()

    async def disconnect(self):
        self.bus.disconnect()

    async def _get_initial_result_sets(self, search_providers: Iterable[GnomeSearchProvider], search_terms: list[str],
                                       timeout: float = 30) -> AsyncGenerator[Result[list[str]], None]:
        """Query all the search providers for the same query. Yield results as they arrive"""
        tasks: dict[asyncio.Task, GnomeSearchProvider] = {}

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

        tasks: dict[asyncio.Task, GnomeSearchProvider] = {}

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


class GnomeSearchProviderInteracterStateful(GnomeSearchProviderInteracter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.previous_search_results: list[Result[list[str]]] = []
        self.previous_search_providers_that_did_not_finish: set[GnomeSearchProvider] = set()

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


async def main():
    gnome_search_provider = GnomeSearchProviderInteracterStateful()
    await gnome_search_provider.init()
    results_generator = gnome_search_provider.get_initial_result_sets(["2+2"], timeout=10)
    async for result in results_generator:
        print(result.search_provider.provider_info.bus_name)
        if not result.error:
            print(result.results)
        else:
            print(f"Provider failed: {result.error}")
        print()

    results_generator = gnome_search_provider.get_subsearch_result_sets(["2+2+3"], timeout=10)
    async for result in results_generator:
        print(result.search_provider.provider_info.bus_name)
        if not result.error:
            print(result.results)
        else:
            print(f"Provider failed: {result.error}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
