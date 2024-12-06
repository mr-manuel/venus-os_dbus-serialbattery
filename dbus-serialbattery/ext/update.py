# This script is used to update single files from different submodules

import os
import requests
import tarfile
import shutil

files = [
    # path: path where the file will be saved
    # url: URL to the file
    {"path": "/", "url": "https://raw.githubusercontent.com/pyhys/minimalmodbus/refs/heads/master/minimalmodbus.py"},
    {"path": "/", "url": "https://raw.githubusercontent.com/python/typing_extensions/refs/heads/main/src/typing_extensions.py"},
]

modules = [
    # name: module name
    # user/repository: GitHub user/repository
    # extract: extract only this folder from the tarball
    {"name": "aenum", "user/repository": "ethanfurman/aenum", "extract": "/aenum"},
    {"name": "bleak", "user/repository": "hbldh/bleak", "extract": "/bleak"},
    {"name": "can", "user/repository": "hardbyte/python-can", "extract": "/can"},
    {"name": "velib_python", "user/repository": "victronenergy/velib_python", "extract": ""},
    {"name": "venus-os_dbus-serialbattery_gui-v2", "user/repository": "mr-manuel/venus-os_dbus-serialbattery_gui-v2", "extract": ""},
    {"name": "venus-os_overlay-fs", "user/repository": "mr-manuel/venus-os_overlay-fs", "extract": ""},
    {"name": "wrapt", "user/repository": "GrahamDumpleton/wrapt", "extract": "/src/wrapt"},
]

root_dir = "./dbus-serialbattery/ext"
temp_dir = f"{root_dir}/.temp"


def update_file(dir, url):
    # extract the filename from the URL
    filename = url.split("/")[-1]

    print(f"Updating file: {filename}...")

    # create the directory if it doesn't exist
    if not os.path.exists(dir):
        os.makedirs(dir)

    # full path for the file to be saved
    file_path = os.path.join(dir, filename)

    # download the file
    response = requests.get(url)
    response.raise_for_status()  # raises an HTTPError if the response status code is 4XX/5XX

    # write the file content to disk
    with open(file_path, "wb") as file:
        file.write(response.content)

    print(f'File "{filename}" downloaded and saved in "{dir}".')


def update_module(name, repo_url, extract):
    print(f"Updating module: {name}...")

    # Fetch the latest release information from the GitHub API
    api_url = f"https://api.github.com/repos/{repo_url}/releases/latest"
    response = requests.get(api_url)

    # Get repo name
    repo_name = repo_url.split("/")[1]

    if response.status_code == 404:
        # No releases found, fallback to tags
        api_url = f"https://api.github.com/repos/{repo_url}/tags"
        response = requests.get(api_url)
        response.raise_for_status()  # raises an HTTPError if the response status code is 4XX/5XX
        tags_info = response.json()

        if tags_info:
            # Extract the latest tag name
            tag_name = tags_info[0]["name"]
            # Construct the URL for the tarball
            tarball_url = f"https://github.com/{repo_url}/archive/refs/tags/{tag_name}.tar.gz"
        else:
            # Get repository default branch
            api_url = f"https://api.github.com/repos/{repo_url}"
            response = requests.get(api_url)
            response.raise_for_status()
            repo_info = response.json()
            default_branch = repo_info["default_branch"]
            tag_name = default_branch
            # Construct the URL for the tarball
            tarball_url = f"https://github.com/{repo_url}/archive/refs/heads/{default_branch}.tar.gz"

    else:
        response.raise_for_status()  # raises an HTTPError if the response status code is 4XX/5XX
        release_info = response.json()
        tag_name = release_info["tag_name"]

        # Construct the URL for the tarball
        tarball_url = f"https://github.com/{repo_url}/archive/refs/tags/{tag_name}.tar.gz"

    # Full path for the tarball to be saved
    tarball_name = f"{repo_name}-{tag_name}.tar.gz"
    tarball_path = os.path.join(temp_dir, tarball_name)

    # Download the tarball
    response = requests.get(tarball_url)
    response.raise_for_status()  # raises an HTTPError if the response status code is 4XX/5XX

    # Write the tarball content to disk
    with open(tarball_path, "wb") as file:
        file.write(response.content)

    # Extract the tarball only the specified folder
    print(f"|- Extract {tarball_path}")
    with tarfile.open(tarball_path, "r:gz") as tar:
        members = tar.getmembers()
        first_folder = None
        for member in members:
            if member.isdir():
                first_folder = member.name.split("/")[0]
                break
        if first_folder:
            members = [m for m in members if m.name.startswith(first_folder + extract)]
            tar.extractall(path=temp_dir, members=members)

    # Module destination directory
    directory_name = f"{root_dir}/{name}"

    # Clean the directory if it exists
    if os.path.exists(directory_name):
        shutil.rmtree(directory_name)

    # Create the directory
    os.makedirs(directory_name)

    # Path to the extracted folder
    extracted_folder = f"{temp_dir}/{first_folder}{extract}"

    # move content from {temp_dir}/{repo_name}-{tag_name}{extract} to {directory_name}
    print(f'|- Move content from "{extracted_folder}" to "{directory_name}"')

    # Move the contents of the extracted folder to the target directory
    for item in os.listdir(extracted_folder):
        s = os.path.join(extracted_folder, item)
        d = os.path.join(directory_name, item)
        shutil.move(s, d)

    print(f'|- Tarball "{tag_name}.tar.gz" from "{tarball_url}" downloaded and saved in "{directory_name}".')
    print()


if __name__ == "__main__":

    print()

    # create the directory if it doesn't exist
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    for entry in files:
        update_file(root_dir + entry["path"], entry["url"])

    print()

    for entry in modules:
        update_module(entry["name"], entry["user/repository"], entry["extract"])

    # remove the temporary directory
    print("Remove temporary directory")
    shutil.rmtree(temp_dir)

    print()
