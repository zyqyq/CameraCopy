# CameraCopy

CameraCopy is a cross-platform desktop application for copying photos and videos from
camera cards (and other mounted storage volumes.) to an organized destination folder. It supports
verified copies, dual-volume clone workflows, metadata-based folders, sidecars, optional source
cleanup, and guarded post-copy formatting.<br>
<img width="652" height="292" alt="{238BE105-6884-4BB6-AAD8-3F434F9CE498}" src="https://github.com/user-attachments/assets/4f594f39-f818-43e5-88bb-38c4f05c657a" /><br>
<img width="1002" height="672" alt="{B954D231-7E0E-4C66-837E-976557948811}" src="https://github.com/user-attachments/assets/7daa73f8-f75d-4e09-b412-41d9489dd04e" /><br>
<img width="862" height="712" alt="{F852E701-8BBA-47A0-87B0-D7F5C007A775}" src="https://github.com/user-attachments/assets/1c3a7889-335b-48d0-8621-4e7622d6c648" />


## Features

- Copy from one or two mounted volumes.
- Dual-volume clone verification with mismatch handling.
- Recursive scanning with configurable include and exclude patterns.
- Date-based destination folders with configurable naming.
- Ratings from Adobe XMP and RapidRaw `.rrdata` sidecars.
- Optional embedded ratings and timestamps through ExifTool.
- Optional copying of matching XMP and RapidRaw sidecars.
- Existing-file handling: ask, skip, overwrite, or keep both.
- Redundant backups: write every copied file to one or more extra folders, so a single
  card ends up on several disks in one pass.
- SHA-256 verification and temporary-file writes.
- Resumable file copies: after a cancel, crash, or power failure the data that was
  already written is kept as a partial file and continued from that byte offset.
- Interrupted-copy recovery: the state of a running copy is recorded outside the
  destination, so the same job can be restarted and only the remaining files are copied.
- Optional source cleanup after successful preservation.
- Guarded formatting after a clean copy operation.
- Per-operation logs, progress, transfer speed, ETA, and cancellation.
- System, light, and dark themes with customizable copy output colors.

## Windows requirements

The Windows installer and portable package are self-contained; Python is not required.

- A 64-bit Windows system.
- CameraCopy runs without Administrator privileges. If Windows denies a format operation,
  CameraCopy requests UAC elevation for that operation only.
- [ExifTool](https://exiftool.org/install.html) is optional and enables embedded ratings
  and capture timestamps.

Download either the installer or portable archive from the repository's Releases page:

```text
CameraCopy-Setup-<version>.exe
CameraCopy-<version>-windows-x86_64-portable.zip
```

The portable archive must be extracted before use. Keep `CameraCopy.exe` together with the
files in its distribution folder.

## Linux requirements

Native x86-64 packages are built for Debian/Ubuntu, Fedora/RPM-based systems, and Arch
Linux. Package managers install the required runtime libraries automatically.
CameraCopy uses UDisks2 for unmounting, formatting, and remounting removable media.
Formatting may require authorization through the system's Polkit configuration.
[ExifTool](https://exiftool.org/) is optional and enables embedded ratings and
capture timestamps.

Install a downloaded package with the appropriate command:

```bash
# Debian / Ubuntu
sudo apt install ./cameracopy_<version>_amd64.deb

# Fedora / RPM-based distributions
sudo dnf install ./cameracopy-<version>-1.x86_64.rpm

# Arch Linux
sudo pacman -U ./cameracopy-<version>-1-x86_64.pkg.tar.zst
```

Start CameraCopy from the desktop menu or run:

```bash
cameracopy
```
### Manual Linux installation

The supplied Linux packages are recommended because they install CameraCopy's dependencies
automatically. To install the source tree manually as a normal system application, first make sure Python
3.11 or newer and the dependencies listed in `requirements.txt` are installed.

From the extracted CameraCopy source directory, run:

```bash
sudo mkdir -p /usr/lib/cameracopy
sudo cp -R cameracopy2 /usr/lib/cameracopy/

sudo install -m 755 packaging/linux/cameracopy /usr/bin/cameracopy
sudo install -m 644 packaging/linux/cameracopy.desktop \
    /usr/share/applications/cameracopy.desktop

sudo cp -R packaging/linux/icons/hicolor/* /usr/share/icons/hicolor/
```

CameraCopy can then be opened from the desktop application menu or started with:

```bash
cameracopy
```

## Usage

1. Open **Settings**.
2. Set the source subfolder, commonly `DCIM`, or leave it empty to scan the selected volume root.
3. Choose the destination folder and file patterns.
4. Configure folder naming, metadata, verification, sidecar, and collision options.
5. Select the first source volume in the main window.
6. Optionally select a second volume and enable clone mode.
7. Start the copy and review the final summary before removing or formatting media.

### Continuing an interrupted copy

If a copy is cancelled, interrupted by a crash, or stopped by a power failure, CameraCopy
remembers what it had already preserved:

1. Reconnect the same source volume(s) and start CameraCopy again.
2. **Resume interrupted copy** appears next to the volume selectors. Its tooltip shows the
   destination and how many files the earlier run already copied.
3. Select it to repeat the saved job. CameraCopy restores the settings of that run, skips
   the files that are already complete, and continues partially written files at the byte
   offset that is really on disk.
4. Select **Discard session** to delete the recovery information and any unfinished partial
   files instead. Files that were already copied to the destination are kept.

Recovery is stored in the per-user state directory next to the operation logs, never in the
destination folder, and it is deleted as soon as the copy finishes successfully. Both
behaviours can be turned off in **Settings** (**Resume interrupted file copies** on the
Files tab and **Recover interrupted copy jobs** on the Advanced tab).

### Redundant backups

A copy normally writes each file once. Enable **Redundant backup** on the
Source/Destination tab to write every copied file to one or more extra folders as well, so
a single card is preserved on more than one disk in a single pass:

1. In **Settings**, tick **Also write every copied file to the backup folders below**.
2. Add each backup folder, for example the folder of a second external disk, and choose
   whether they are written **at the same time** (parallel writes, faster) or **one after
   another** (gentler on slow disks).
3. Start the copy as usual. Dated folder names, and names changed by the collision policy,
   are reproduced in every backup folder.

Rules that keep the copy safe:

- Every configured backup folder must be available and writable before the copy starts. If
  one is missing, CameraCopy stops before writing anything and reports which folder failed.
- A file that already exists in a backup folder is compared with the source by hash (or by
  size when hashing is off). Identical files are verified and left untouched, so a repeated
  run does not rewrite them.
- When an existing backup copy differs, the collision policy decides. **Replace existing
  files** and **Keep both** are honoured; **Always ask** and **Skip existing files** report
  the file as a failure rather than silently overwriting or skipping it.
- Source files are removed only after **every** backup folder holds the file. A failed
  backup keeps the source, marks the file as failed, and warns before formatting the volume.

The final summary lists each backup folder with how many files it received, verified, or
failed to receive.


## Building

### Development environment

CameraCopy requires [Python 3.11 or newer](https://www.python.org/downloads/) and
[Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m cameracopy2
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## Safety and disclaimer

CameraCopy handles valuable and sometimes irreplaceable files. Verify copied files
independently before deleting or formatting source media, and test destructive workflows
with disposable media first.

The software is provided without warranty. The authors and contributors are not responsible
for lost, damaged, corrupted, or overwritten data, hardware problems, or other losses
resulting from its use. **USE AT YOUR OWN RISK!**
