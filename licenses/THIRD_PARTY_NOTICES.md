# Third-party software

Isaac-Link's original code is released under the MIT license in [LICENSE](../LICENSE).
Dependencies retain their own licenses.

- **PySide6 Essentials / Shiboken / Qt 6.11.2**: Qt Widgets, Gui, Core and their runtime dependencies are distributed as shared libraries in `_internal`. See [LGPL v3](QT-LGPL-3.0.txt), [GPL v3](QT-GPL-3.0.txt), [PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/?h=6.11.2) and [Qt source](https://code.qt.io/cgit/qt/qtbase.git/?h=6.11.2). No Qt library source has been modified. Users may replace compatible libraries and rebuild the application using the supplied source and PyInstaller spec; debugging library modifications is not restricted by this project.
- **cryptography 50.0.1**: Apache 2.0 or BSD. See [license](CRYPTOGRAPHY-LICENSE.txt), [Apache terms](CRYPTOGRAPHY-APACHE.txt), [BSD terms](CRYPTOGRAPHY-BSD.txt), and [upstream source](https://github.com/pyca/cryptography). Used for Ed25519 release verification.

- **Frida 17.17.0**: wxWindows Library Licence 3.1. See [included license](FRIDA-COPYING.txt) and [upstream source](https://github.com/frida/frida-python/tree/17.17.0). Frida includes additional components covered by upstream notices; this project does not relicense them.
- **CPython**: Python Software Foundation License and bundled component notices. See [Python license](https://docs.python.org/3/license.html). The Windows executable bundles a Python runtime.
- **PyInstaller 6.19.0**: GPL with the bootloader distribution exception. See [upstream license](https://github.com/pyinstaller/pyinstaller/blob/v6.19.0/COPYING.txt). Used to build the executable, not required to run from source.

The game and Steam are separately installed software and are not distributed in this repository.
