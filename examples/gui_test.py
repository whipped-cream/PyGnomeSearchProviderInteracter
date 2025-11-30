import time
from abc import ABC, abstractmethod
from typing import Callable

import dbus_next
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, Pango, GioUnix

import asyncio
from gi.events import GLibEventLoopPolicy

import html

asyncio.set_event_loop_policy(GLibEventLoopPolicy())

import gnomesearchclient

heading_attrlist = Pango.AttrList()
heading_attrlist.insert(Pango.attr_scale_new(2))

class MoreInfoBin(Adw.Bin):
    def __init__(self, result_meta: gnomesearchclient.ResultMeta, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)

        list_scrollbox = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        list_view = Gtk.ListBox(vexpand=True, hexpand=True)
        list_scrollbox.set_child(list_view)

        main_box.append(list_scrollbox)

        for key, value in result_meta.items():
            value: dbus_next.Variant
            list_view.append(
                Adw.ActionRow(title=html.escape(key), subtitle=html.escape(repr(value)), selectable=False)
            )


class ResultInfoDialog(Adw.Dialog):
    def __init__(self, result: gnomesearchclient.Result[list[str]], *args, **kwargs):
        super().__init__(presentation_mode=Adw.DialogPresentationMode.FLOATING, *args, **kwargs)

        super().set_size_request(600, 400)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, margin_start=24, margin_end=24, margin_bottom=24)
        main_page = Adw.ToolbarView()
        main_page.add_top_bar(Adw.HeaderBar())
        main_page.set_content(main_box)
        super().set_child(main_page)

        center_box = Gtk.CenterBox(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        desktop_app_info: Gio.DesktopAppInfo = GioUnix.DesktopAppInfo.new(result.search_provider.desktop_id)
        center_box.set_start_widget(Gtk.Image(icon_name=desktop_app_info.get_icon().props.names[0], icon_size=Gtk.IconSize.LARGE))
        center_box.set_center_widget(Gtk.Label(label=desktop_app_info.get_display_name()))
        self.launch_button = Gtk.Button(icon_name="go-next-symbolic")
        center_box.set_end_widget(self.launch_button)

        main_box.append(center_box)

        self.more_info_bin = Adw.Bin()
        main_box.append(self.more_info_bin)
        self.more_info_bin.set_child(Adw.Spinner(hexpand=True, vexpand=True))

        self.result = result

    async def init(self, result_index: int, on_launch_action):
        result_metas = await self.result.search_provider.get_result_metas([self.result.results[result_index]])

        self.launch_button.connect("clicked", on_launch_action, self.result, result_index)

        if len(result_metas) > 0:
            self.more_info_bin.set_child(MoreInfoBin(result_metas[0]))
        else:
            self.more_info_bin.set_child(Gtk.Label(label="Provider returned no results. Try searching again"))


class ResultListItem(Adw.ActionRow):
    def __init__(self, text: str, *args, **kwargs):
        super().__init__(title=text, activatable=True, selectable=False, *args, **kwargs)


class ResultList(Adw.Bin):
    def __init__(self, result: gnomesearchclient.Result[list[str]], *args, **kwargs):
        super().__init__(*args, **kwargs)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(box)

        center_box = Gtk.CenterBox(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        desktop_app_info: Gio.DesktopAppInfo = GioUnix.DesktopAppInfo.new(result.search_provider.desktop_id)
        center_box.set_start_widget(Gtk.Image(icon_name=desktop_app_info.get_icon().props.names[0], icon_size=Gtk.IconSize.LARGE))
        center_box.set_center_widget(Gtk.Label(label=desktop_app_info.get_display_name()))

        box.append(center_box)

        results_bin = Adw.Bin(margin_start=30)
        box.append(results_bin)

        results_listbox = Gtk.ListBox()
        results_bin.set_child(results_listbox)

        for i, res in enumerate(result.results[:10]):
            txt = res.replace("&", "&amp;")
            item = ResultListItem(txt)
            item.connect("activated", self.on_result_clicked, result, i)
            results_listbox.append(item)
        if len(result.results) > 10:
            results_listbox.append(ResultListItem(f"and {len(result.results) - 10} more ..."))

    def on_result_clicked(self, _, result: gnomesearchclient.Result[list[str]], index: int):
        asyncio.create_task(self._on_result_clicked(result, index))

    def on_launch_clicked(self, _, result: gnomesearchclient.Result[list[str]], index: int):
        asyncio.create_task(self._on_launch_clicked(result, index))

    async def _on_result_clicked(self, result: gnomesearchclient.Result[list[str]], result_index: int):
        result_info_dialog = ResultInfoDialog(result)
        result_info_dialog.present(self.get_parent())
        await result_info_dialog.init(result_index, self.on_launch_clicked)

    async def _on_launch_clicked(self, result: gnomesearchclient.Result[list[str]], result_index: int):
        await result.search_provider.activate_result(result.results[result_index], result.query, int(time.time()))



class SearchPage(Adw.NavigationPage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_bin = Adw.Bin()
        super().set_child(main_bin)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        main_bin.set_child(toolbar_view)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.BASELINE_FILL,
                           valign=Gtk.Align.BASELINE_FILL, vexpand=True, hexpand=True, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        toolbar_view.set_content(main_box)

        entry_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER)
        entry_label = Gtk.Label(label="Search Query", attributes=heading_attrlist)
        entry_box.append(entry_label)
        self.entry = Gtk.Entry()
        self.entry.connect("activate", lambda x: asyncio.create_task(self._on_search_clicked()))
        entry_box.append(self.entry)
        main_box.append(entry_box)

        entry_control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER,
                                    valign=Gtk.Align.CENTER, vexpand=True, hexpand=True)
        entry_search = Gtk.Button(label="Search")
        entry_search.connect("clicked", lambda x: asyncio.create_task(self._on_search_clicked()))
        entry_control_box.append(entry_search)
        entry_box.append(entry_control_box)

        self.output_bin = Adw.Bin(vexpand=True)
        # output_scrollbox = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        # self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # output_scrollbox.set_child(self.results_box)
        main_box.append(self.output_bin)

    @abstractmethod
    def _on_search_clicked(self):
        pass


class SearchOnePage(SearchPage):
    def __init__(self, provider: gnomesearchclient.Provider, *args, **kwargs):
        self.provider = provider
        self.application = GioUnix.DesktopAppInfo.new(provider.desktop_id)

        super().__init__(title=f"{self.application.get_display_name()} Test", *args, **kwargs)


    async def _on_search_clicked(self):
        self.output_bin.set_child(Adw.Spinner(hexpand=True, vexpand=True))
        query = [self.entry.get_text()]
        result = await self.provider.get_initial_result_set(query)
        scrolled_window = Gtk.ScrolledWindow()
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled_window.set_child(results_box)
        results_box.append(ResultList(gnomesearchclient.Result(self.provider, query, result)))
        self.output_bin.set_child(scrolled_window)

class SearchAllPage(SearchPage):
    def __init__(self, client: gnomesearchclient.ClientStateful, *args, **kwargs):
        self.client = client

        super().__init__(title="Test all providers", *args, **kwargs)


    async def _on_search_clicked(self):
        self.output_bin.set_child(Adw.Spinner(hexpand=True, vexpand=True))
        query = [self.entry.get_text()]
        results_box = None

        async for result in self.client.get_subsearch_result_sets(query):
            if results_box is None:
                results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                scrolled_window = Gtk.ScrolledWindow(child=results_box, vexpand=True)
                self.output_bin.set_child(scrolled_window)

            results_box.append(ResultList(result))


class SearchProviderSelector(Adw.NavigationPage):
    def __init__(self, client: gnomesearchclient.ClientStateful,
                 on_search_all_selected: Callable[[], None], on_search_one_selected: Callable[[gnomesearchclient.Provider], None],
                 *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = client

        self.set_title("Search Provider Selector")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                           vexpand=True, hexpand=True,
                           margin_top=24, margin_bottom=24,
                           halign=Gtk.Align.CENTER,
                           valign=Gtk.Align.BASELINE_FILL,
                           spacing=12)
        self.set_child(main_box)

        heading = Gtk.Label(label="Choose a search provider", attributes=heading_attrlist)
        main_box.append(heading)

        # all_providers_list = Gtk.ListBox()
        # all_providers_list.append(Adw.ButtonRow(title="Search all providers"))
        # main_box.append(all_providers_list)

        list_scrollbox = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        search_provider_list = Gtk.ListBox()
        list_scrollbox.set_child(search_provider_list)
        main_box.append(list_scrollbox)

        search_all_button = Adw.ButtonRow(title="Search all providers", margin_bottom=24)
        search_all_button.connect("activated", on_search_all_selected)
        search_provider_list.append(search_all_button)

        for provider in self.client.providers:
            desktop_info: Gio.DesktopAppInfo = GioUnix.DesktopAppInfo.new(provider.desktop_id)

            provider_button = Adw.ButtonRow(
                selectable=False,
                activatable=True,
                start_icon_name=desktop_info.get_icon().props.names[0],
                title=desktop_info.get_name()
            )

            provider_button.connect("activated", on_search_one_selected, provider)

            search_provider_list.append(provider_button)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, client: gnomesearchclient.ClientStateful, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client

        self.set_title("PyGnomeSearchClient GUI Test")
        self.set_default_size(600, 800)

        main_bin = Adw.Bin()
        self.set_content(main_bin)
        self.main_view = Adw.NavigationView()
        main_bin.set_child(self.main_view)

        self.search_provider_selector = None
        self.search_provider_pages = []

        self.spinner_page = Adw.NavigationPage(child=Adw.Spinner(hexpand=True, vexpand=True), title="Loading...")

        self.main_view.push(self.spinner_page)

        asyncio.create_task(self.init())


    async def init(self):
        await self.client.init()
        self.search_provider_selector = SearchProviderSelector(self.client, self.on_search_all_selected, self.on_search_one_selected)
        self.main_view.push(self.search_provider_selector)


    def on_search_all_selected(self, button):
        page = SearchAllPage(self.client)
        self.main_view.push(page)


    def on_search_one_selected(self, button, provider: gnomesearchclient.Provider):
        page = SearchOnePage(provider)
        self.main_view.push(page)


class Application(Adw.Application):
    def __init__(self):
        self.searcher = gnomesearchclient.ClientStateful(gnomesearchclient.Client())

        super().__init__(application_id="org.example.AdwaitaPyGObject",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self.on_activate)

    def on_activate(self, application):
        win = self.props.active_window
        if not win:
            win = MainWindow(application=application, client=self.searcher)
        win.present()


if __name__ == "__main__":
    app = Application()
    app.run(None)