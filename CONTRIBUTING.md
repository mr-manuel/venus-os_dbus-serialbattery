## Contributing Guidelines

We welcome contributions to dbus-serialbattery! Please follow these steps to help us keep the project organized and high quality:

### How to Contribute

1. **Fork the repository**

   Click the "Fork" button on GitHub and clone your fork locally.

2. **Create a new branch**

   Use a descriptive branch name, e.g. `feature/new-bms-support` or `fix/typo-in-readme`.

3. **Make your changes**

   - Follow the existing code style and structure.
   - Run [Black](https://black.readthedocs.io/en/stable/) and [Flake8](https://flake8.pycqa.org/en/latest/) to check formatting and linting. [Here](https://py-vscode.readthedocs.io/en/latest/files/linting.html) you can find short instructions on how to set up Flake8 and Black Lint checks in VS Code. This will save you a lot of time.
   - Add an entry to the [CHANGELOG.md](https://github.com/mr-manuel/venus-os_dbus-serialbattery/blob/master/CHANGELOG.md) in alphabetical order. Follow the format of existing entries.
   - Add or update documentation if needed.
   - If you add a new BMS, see the [add a new BMS checklist](https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/general/supported-bms#add-by-opening-a-pull-request).

4. **Test your changes**

   Make sure your code runs without errors at least for 24 hours.

5. **Submit a Pull Request (PR)**

   - Push your branch to your fork and open a PR against the `master` branch.
   - Clearly describe your changes and reference any related issues (e.g. #392).
   - If your PR fixes a bug, include `Fixes #issue_number` in the description.

6. **Respond to feedback**

   - Be ready to make changes if maintainers request them.
   - Keep discussions constructive and focused on the code.

### Code Style

- Use [Black](https://black.readthedocs.io/en/stable/) for formatting.
- Use [Flake8](https://flake8.pycqa.org/en/latest/) for linting.
- Write clear, concise comments and docstrings.

### Other Notes

- For major changes, open an issue first to discuss your idea.
- All contributions must be licensed under the project's license.
- Be respectful and collaborative.

Thank you for helping improve dbus-serialbattery!
