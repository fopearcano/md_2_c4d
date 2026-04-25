MD2C4D Bridge — Cinema 4D plugin resources
==========================================

This folder is reserved for Cinema 4D plugin resource files
(description/, strings_*/c4d_strings.str, icons, dialog layouts).

The current MVP registers a single CommandData plugin with no
parameter dialog and no icon, so no resource files are required yet.
The folder is committed empty to lock in the layout for future
iterations:

    c4d_plugin/
    ├── MD2C4D_Bridge.pyp
    ├── README_C4D_INSTALL.md
    └── res/
        ├── description/        (future: parameter dialogs)
        ├── strings_en-US/
        │   └── c4d_strings.str (future: localized strings)
        └── icons/              (future: command icon)
