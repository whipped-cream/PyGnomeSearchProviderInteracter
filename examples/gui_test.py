from abc import ABC, abstractmethod
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, Pango, GioUnix

import asyncio
from gi.events import GLibEventLoopPolicy


asyncio.set_event_loop_policy(GLibEventLoopPolicy())

import gnomesearchclient

heading_attrlist = Pango.AttrList()
heading_attrlist.insert(Pango.attr_scale_new(2))

class SearchPage(Adw.NavigationPage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_bin = Adw.Bin()
        super().set_child(main_bin)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        main_bin.set_child(toolbar_view)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.BASELINE_FILL,
                           valign=Gtk.Align.BASELINE_FILL, vexpand=True, hexpand=True, margin_top=24, margin_bottom=24)
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

        output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.BASELINE_FILL,
                             valign=Gtk.Align.BASELINE_FILL, vexpand=True, hexpand=True)
        self.output_text_buffer = Gtk.TextBuffer()
        output_scrollbox = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        output_text = Gtk.TextView(editable=False, buffer=self.output_text_buffer, hexpand=True, vexpand=True)
        output_scrollbox.set_child(output_text)
        output_box.append(output_scrollbox)
        main_box.append(output_box)

    @abstractmethod
    def _on_search_clicked(self):
        pass


class SearchOnePage(SearchPage):
    def __init__(self, provider: gnomesearchclient.Provider, *args, **kwargs):
        self.provider = provider
        self.application = GioUnix.DesktopAppInfo.new(provider.desktop_id)

        super().__init__(title=f"{self.application.get_display_name()} Test", *args, **kwargs)


    async def _on_search_clicked(self):
        result = await self.provider.get_initial_result_set([self.entry.get_text()])
        self.output_text_buffer.set_text(str(result))

class SearchAllPage(SearchPage):
    def __init__(self, client: gnomesearchclient.ClientStateful, *args, **kwargs):
        self.client = client

        super().__init__(title="Test all providers", *args, **kwargs)


    async def _on_search_clicked(self):
        self.output_text_buffer.set_text("")
        iter = self.output_text_buffer.get_start_iter()

        current_terms = self.entry.get_text()

        async for result in self.client.get_subsearch_result_sets([current_terms]):
            self.output_text_buffer.insert(iter, result.search_provider.provider_info.object_path + "\n")
            self.output_text_buffer.insert(iter, str(result.results) + "\n")


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

        for provider in self.client.search_providers:
            desktop_info: Gio.DesktopAppInfo = GioUnix.DesktopAppInfo.new(provider.desktop_id)

            provider_button = Adw.ButtonRow(
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
        self.searcher = gnomesearchclient.ClientStateful()

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