import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio

from gnome_search_provider_interacter import GnomeSearchProviderInteracter

class TestPage(Adw.NavigationPage):
    def __on_search_clicked(self, button: Gtk.Button):
        pass

    def __init__(self, desktop_id: str, bus_name: str, object_path: str, *args, **kwargs):
        self.application = Gio.DesktopAppInfo(desktop_id)
        self.desktop_id = desktop_id
        self.bus_name = bus_name
        self.object_path = object_path

        super().__init__(title=f"{self.application.get_display_name()}", *args, **kwargs)
        main_bin = Adw.Bin()
        super().set_child(main_bin)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True, hexpand=True, margin_top=24, margin_bottom=24)
        main_bin.set_child(main_box)

        entry_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        entry_label = Gtk.Label(label="Search Query")
        entry_box.append(entry_label)
        self.entry = Gtk.Entry()
        entry_box.append(self.entry)

        entry_control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True, hexpand=True)
        entry_search = Gtk.Button(label="Search")
        entry_search.connect("clicked", self.__on_search_clicked)
        entry_control_box.append(entry_search)
        entry_box.append(entry_control_box)

        output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True, hexpand=True)
        self.output_text_buffer = Gtk.TextBuffer()
        output_scrollbox = Gtk.ScrolledWindow()
        output_text = Gtk.TextView(editable=False, buffer=self.output_text_buffer)
        output_scrollbox.set_child(output_text)
        output_box.append(output_scrollbox)




class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        icon = self.application.get_string("Icon")
        if not icon:
            icon = "image-missing"

        scrolled_window = Gtk.ScrolledWindow()
        list_view = Gtk.ListView()
        scrolled_window.set_child(list_view)

        super().__init__(*args, **kwargs)
        self.set_default_size(600, 400)
        self.set_title("Adwaita PyGObject Example")

        # Create a header bar
        header_bar = Gtk.HeaderBar()
        # self.set_titlebar(header_bar)

        # Create a title widget for the header bar
        title_widget = Adw.WindowTitle(title="My Adwaita App", subtitle="A Simple Example")
        header_bar.set_title_widget(title_widget)

        # Create a content area (e.g., a Gtk.Box)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        self.set_content(content_box)

        # Add a label to the content area
        label = Gtk.Label(label="Welcome to your Adwaita PyGObject application!")
        content_box.append(label)

        # Add a button to the content area
        button = Gtk.Button(label="Click Me!")
        button.connect("clicked", self.on_button_clicked)
        content_box.append(button)

    def on_button_clicked(self, widget):
        print("Button clicked!")
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Hello There!",
            body="You clicked the button!",
            close_response="ok",
        )
        dialog.add_response("ok", "OK")
        dialog.present()


class Application(Adw.Application):
    def __init__(self):
        searcher = GnomeSearchProviderInteracter()

        super().__init__(application_id="org.example.AdwaitaPyGObject",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        win = self.props.active_window
        if not win:
            win = MainWindow(application=app)
        win.present()


if __name__ == "__main__":
    app = Application()
    app.run(None)