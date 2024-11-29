# Surfscape Web Browser

Surfscape is a lightweight and customizable web browser built using PyQt6. It provides essential features for web browsing, including tabbed browsing, bookmarks, history, and customizable settings. Suitable for Tilling Window Managers.

![Surfscape Web Browser](https://raw.githubusercontent.com/machaddr/surfscape/main/screenshots/browser.png)

## Features

- **Tabbed Browsing:** Open multiple web pages in separate tabs.
- **Bookmarks:** Save and manage your favorite web pages.
- **History:** Keep track of your browsing history.
- **Cookies Management:** Manage cookies for better privacy and control.
- **Customizable Settings:** Change the homepage, theme, font, and more.
- **Keyboard Shortcuts:** Use convenient keyboard shortcuts for common actions.

## Dependencies

Before installing Surfscape, make sure you have the following dependencies installed:

- [Python 3.6 or above](https://www.python.org/downloads/)
- [PyQt6](https://pypi.org/project/PyQt6/)
- [PyQt6 WebEngine](https://pypi.org/project/PyQt6-WebEngine/)


You can install these dependencies using `pip`, the Python package installer. Open a terminal or command prompt and run the following command:

```bash
pip install PyQt6 PyQt6-WebEngine
```

Or you can install these dependencies using the package manager of your favorite Linux Distribution.

## Tor Setup
To start Tor via `systemctl` using your Linux Distribution of choice, run the following command:

```bash
sudo systemctl start tor
```

To enable Tor to start at boot, use:

```bash
sudo systemctl enable tor
```

Alternatively, on Windows, you can configure Tor to start at boot by creating a shortcut to `tor.exe` in the Startup folder. Follow these steps:

1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Create a shortcut to `tor.exe` in the Startup folder.

This will ensure Tor starts automatically when you log in to your Windows account.

After these steps you can enable or disable Tor via Browser Settings.

## License
This library is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3. See [LICENSE](LICENSE) for details.

## Author
Surfscace is developed and maintained by André Machado. <br />You can contact him at sedzcat@gmail.com.
