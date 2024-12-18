# Surfscape Web Browser

Surfscape is a lightweight and customizable web browser built using PyQt6. It provides essential features for web browsing, including tabbed browsing, bookmarks, history, and customizable settings. Suitable for Tilling Window Managers under Linux or *BSD.

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
- [Adblockparser](https://pypi.org/project/adblockparser/)

You can install these dependencies using `pip`, the Python package installer. Open a terminal or command prompt and run the following command:

```bash
pip install PyQt6 PyQt6-WebEngine adblockparser
```

Or you can install these dependencies using the package manager of your favorite Linux Distribution.

## Tor Setup

To configure Tor to use specific ports and enable cookie authentication, add the following lines to your `torrc` file:

```
ControlPort 9051
SocksPort 9050
CookieAuthentication 1
```

The `torrc` file is typically located in `/etc/tor/` on Linux or in the HOME directory on Windows.

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

After these steps you can enable or disable Tor via Surfscape Browser Settings.

## I2P Setup

### Linux

1. **Install I2P:**
    You can install I2P using your distribution's package manager. For example, on Debian-based systems, run:
    ```bash
    sudo apt update
    sudo apt install i2p
    ```

2. **Start I2P:**
    To start I2P, use the following command:
    ```bash
    i2prouter start
    ```

3. **Enable I2P to start at boot:**
    To ensure I2P starts automatically at boot, use:
    ```bash
    sudo systemctl enable i2p
    ```

4. **Configure I2P:**
    Open your web browser and navigate to `http://127.0.0.1:7657` to access the I2P router console. Configure your I2P settings as needed.

### Windows

1. **Download I2P:**
    Download the I2P installer from the [official I2P website](https://geti2p.net/en/download).

2. **Install I2P:**
    Run the installer and follow the on-screen instructions to install I2P.

3. **Start I2P:**
    After installation, start I2P from the Start Menu or by running `i2prouter` from the command prompt.

4. **Configure I2P:**
    Open your web browser and navigate to `http://127.0.0.1:7657` to access the I2P router console. Configure your I2P settings as needed.

5. **Enable I2P to start at boot:**
    To configure I2P to start at boot, create a shortcut to `i2prouter.exe` in the Startup folder. Follow these steps:
    1. Press `Win + R`, type `shell:startup`, and press Enter.
    2. Create a shortcut to `i2prouter.exe` in the Startup folder.

After these steps, you can enable or disable I2P via Surfscape Browser Settings.

## Contributing

If you would like to contribute, please follow these steps:

1. **Fork the repository** on GitHub.
2. **Clone your forked repository** to your local machine.
3. **Create a new branch** for your feature or bugfix:
    ```bash
    git checkout -b feature-name
    ```
4. **Make your changes** and commit them with clear and descriptive messages.
5. **Push your changes** to your forked repository:
    ```bash
    git push origin feature-name
    ```
6. **Create a pull request** on GitHub, describing your changes and the problem they solve.

Please ensure your code adheres to our coding standards and includes appropriate tests. We will review your pull request and provide feedback.

Thank you for contributing to Surfscape!

## License
This library is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3. See [LICENSE](LICENSE) for details.

## Author
Surfscace is developed and maintained by André Machado. <br />You can contact him at sedzcat@gmail.com.
