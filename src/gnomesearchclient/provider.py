__all__ = ["Provider", "ProviderInfo"]

from dataclasses import dataclass
from typing import Optional, TypedDict

from dbus_next.aio import MessageBus, ProxyObject
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


class ResultMeta(TypedDict, total=False):
    """
    Class for the return type of the get_result_metas function.

    - "id": the result ID

    - "name": the display name for the result

    - "icon": a serialized GIcon (see g_icon_serialize()), or alternatively,

    - "gicon": a textual representation of a GIcon (see g_icon_to_string()), or alternatively,

    - "icon-data": a tuple of type (iiibiiay) describing a pixbuf with width, height, rowstride, has-alpha, bits-per-sample, n-channels, and image data

    - "description": an optional short description (1-2 lines)

    - "clipboardText": an optional text to send to the clipboard on activation
    """
    id: str
    name: str
    icon: str
    gicon: str
    icon_data: tuple[int, int, int, bool, int, int, bytes]
    description: str
    clipboardText: str


@dataclass(frozen=True)
class ProviderInfo:
    desktop_id: str
    bus_name: str
    object_path: str


class Provider:
    def __init__(self, desktop_id: str, bus_name: str, object_path: str, bus: MessageBus):
        self.provider_info = ProviderInfo(desktop_id, bus_name, object_path)
        self.bus = bus
        self.search_interface: Optional[ProxyObject] = None

    async def init(self) -> None:
        proxy_object = self.bus.get_proxy_object(self.provider_info.bus_name,
                                                 self.provider_info.object_path,
                                                 UNIVERSAL_INTROSPECTION)
        self.search_interface = proxy_object.get_interface("org.gnome.Shell.SearchProvider2")

    def __eq__(self, other):
        return isinstance(other, Provider) and self.provider_info == other.provider_info

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

    async def get_subsearch_result_set(self, previous_search_results: list[str], current_search_terms: list[str]) -> list[str]:
        """
        Refine the initial search after the user types in more characters in the search entry.

        :param previous_search_results: List of the previous search results returned from this or the ``get_initial_result_set()`` function.
        :param current_search_terms: Updated search terms.
        :return: List of updated search results.
        """
        return await self.search_interface.call_get_subsearch_result_set(previous_search_results, current_search_terms)

    async def get_result_metas(self, result_ids: list[str]) -> list[ResultMeta]:
        """
        Get detailed information about the results.

        The result is a list of dictionaries, one for each input result_id.

        :param result_ids: Result IDs of the previously completed searches.
        :return: List of dictionaries.
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
