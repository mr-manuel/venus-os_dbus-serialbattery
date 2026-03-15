import re
import os
import glob

qml_dir = r"c:\Users\Manuel\Nextcloud\01_Privat\09_GitHub\venus-os_dbus-serialbattery\dbus-serialbattery\qml\gui-v2"
files = glob.glob(os.path.join(qml_dir, "**", "*.qml"), recursive=True)

total_replacements = 0

for filepath in files:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    new_lines = []
    i = 0
    replacements = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a //% "..." line
        pct_match = re.match(r'^(\s*)//% "(.+)"', line)
        if pct_match:
            translation = pct_match.group(2)

            # Look ahead for qsTrId("dbus_serialbattery...") - possibly after //: lines
            j = i + 1
            while j < len(lines) and re.match(r"^\s*//:.*", lines[j]):
                j += 1

            if j < len(lines):
                qstrid_match = re.search(r'qsTrId\("dbus_serialbattery[^"]*"\)', lines[j])
                if qstrid_match:
                    # Replace //% with // in the current line
                    new_lines.append(line.replace("//%", "//", 1))
                    # Skip any //: lines in between
                    i += 1
                    while i < j:
                        i += 1
                    # Replace qsTrId(...) with the literal string
                    new_line = re.sub(r'qsTrId\("dbus_serialbattery[^"]*"\)', '"' + translation + '"', lines[j])
                    new_lines.append(new_line)
                    replacements += 1
                    i += 1
                    continue

        new_lines.append(line)
        i += 1

    new_content = "\n".join(new_lines)
    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        folder = os.path.basename(os.path.dirname(filepath))
        print(f"  {replacements} replacements in {folder}/{os.path.basename(filepath)}")
        total_replacements += replacements

print(f"Total: {total_replacements} replacements across {len(files)} files")
