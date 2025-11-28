# PyGnomeSearchClient

PyGnomeSearchClient is 
a Python package for interacting with Gnome search providers outside the Gnome Shell 
environment. This package is targeted mostly at users of compositors with custom widgets, 
especially [Ignis](https://github.com/ignis-sh/ignis) since that's what I currently use.

## Rationale
Gnome search providers provide a simple-to-use API for searching various apps on the system 
but is currently limited to use on Gnome Shell. Even without Gnome Shell installed or running, 
most apps that provide search providers still register their search provider interfaces on 
DBus and still place their search configuration files in deterministic places, meaning 
that a different app could interact with them. 
This package aims to create a wrapper around the DBus calls used to interact with the providers.

Gnome search providers are fairly widely used. 
On my system, the installed search providers are:
- [Files (Nautilus)](https://apps.gnome.org/Nautilus/)
- [Boxes](https://apps.gnome.org/en/Boxes/)
- [Calendar](https://apps.gnome.org/en/Calendar/)
- [Cartridges](https://github.com/kra-mo/cartridges/)
- [Clocks](https://apps.gnome.org/en/Clocks/)
- [Firefox](https://www.firefox.com) ([broken?](https://github.com/NixOS/nixpkgs/issues/314083))
- [Passwords and Keys (Seahorse)](https://gitlab.gnome.org/GNOME/seahorse)
- [Qalculate-gtk!](https://github.com/Qalculate/qalculate-gtk)
- [Settings](https://apps.gnome.org/en/Settings/)
- [Software](https://apps.gnome.org/en/Software/)
- [Web (Epiphany)](https://apps.gnome.org/en/Epiphany/)

Any of these, in isolation, could be easily coded into a desktop UI framework, but maintaining 
dozens of different search providers becomes taxing. 
Additionally, adding a new provider does not mean changing your dotfiles at all. 
Rolling your own search provider is also fairly simple, requiring only that a DBus service be registered 
and a config file be placed in some location.

## Usage

TODO

## Documentation

Gnome search providers place an `ini` file in one of a number of locations, generally 
`/usr/share/gnome-shell/search-providers` if installed globally. 
The file has the structure:
```ini
[Shell Search Provider]
DesktopId=xxx.desktop
BusName=xxx.SearchProvider2 (generally)
ObjectPath=/xx/xxx/SearchProvider
Version=2
```

The DBus interface is described by Gnome [here](https://developer.gnome.org/documentation/tutorials/search-provider.html),
but the gist of it is that, under the bus name above, providers register methods `GetInitialResultSet`, 
`GetSubsearchResultSet`, `GetResultMetas`, `ActivateResult`, and `LaunchSearch`.
This package provides wrappers for these methods and collects search providers while optionally 
maintaining state information.

## Contributing

Please open an issue for any bugs or feature requests.
If you know Python and PyGObject, feel free to open a PR.