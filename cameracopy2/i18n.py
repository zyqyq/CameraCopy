"""Runtime internationalisation for CameraCopy.

The application was written with hard-coded English strings.  Rather than
rewriting every call site, this module installs a thin translation layer that
intercepts the Qt APIs used to push text into widgets and translates the text
on the way in.  The English source string is remembered on the widget so the
whole interface can be re-translated instantly when the user switches language.

Design notes
------------
* English text is always the single source of truth.  :func:`translate` maps
  English -> Chinese when the active language is Chinese and returns the input
  unchanged for English, which makes switching back and forth lossless.
* Internal logic (log classification, config keys, file patterns, ...) keeps
  operating on the original English strings because translation only happens at
  the moment text is handed to a widget.
* Translation never raises: an unknown string is simply passed through.
"""

from __future__ import annotations

import re
from typing import Any, Callable

DEFAULT_LANGUAGE = "zh_CN"

#: Language code -> label shown in the settings dialog (never translated).
LANGUAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("zh_CN", "简体中文"),
    ("en", "English"),
)

SUPPORTED_LANGUAGES: frozenset[str] = frozenset(code for code, _ in LANGUAGE_LABELS)

_current_language: str = DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# Translation catalogue (English -> Simplified Chinese)
# ---------------------------------------------------------------------------

TRANSLATIONS: dict[str, str] = {
    # -- generic words -----------------------------------------------------
    "Add": "添加",
    "Remove": "移除",
    "Reset": "重置",
    "Cancel": "取消",
    "Cancelled": "已取消",
    "Cancelling…": "正在取消…",
    "Close": "关闭",
    "Copy": "复制",
    "Skip": "跳过",
    "None": "（无）",
    "Automatic": "自动",
    "Not configured": "未配置",
    "Ready": "就绪",
    "Warning": "警告",
    "Error": "错误",
    "Information": "信息",
    "File": "文件",
    "Preview": "预览",
    "Settings": "设置",
    "Files": "文件",
    "Custom": "自定义",
    "Processing": "正在处理",
    "Scanning": "正在扫描",
    "Copying": "正在复制",
    "Verifying": "正在校验",
    "Removing": "正在删除",
    "Formatting": "正在格式化",
    "Scanning...": "正在扫描…",
    "Copying...": "正在复制…",
    "Verifying...": "正在校验…",
    "Removing...": "正在删除…",
    "Processing...": "正在处理…",
    "Preview unavailable": "无法预览",
    "No primary source selected": "未选择第一个源卷",
    "No secondary source selected": "未选择第二个源卷",
    "No primary volume selected": "未选择第一个源卷",
    "No secondary volume selected": "未选择第二个源卷",
    "Source": "源",
    "Current file": "当前文件",
    "No files": "无文件",
    "unavailable": "不可用",
    "not found": "未找到",
    "Do not format": "不格式化",
    "Language:": "界面语言：",
    # -- volume match methods ----------------------------------------------
    "Device serial": "设备序列号",
    "Filesystem UUID": "文件系统 UUID",
    "Label": "标签",
    "Size": "容量",
    "Device path": "设备路径",
    "Mount point": "挂载点",
    # -- main window -------------------------------------------------------
    "CameraCopy": "CameraCopy",
    "CameraCopy Settings": "CameraCopy 设置",
    "First volume:": "第一个卷：",
    "Second volume:": "第二个卷：",
    "Second volume is a clone of first": "第二个卷是第一个卷的克隆",
    "Remove source files after successful copy": "复制成功后删除源文件",
    "Clone mode:": "克隆模式：",
    "After successful copy:": "复制成功后：",
    "Format after copy:": "复制后格式化：",
    "Start copy": "开始复制",
    "Manual\nrescan": "手动\n重新扫描",
    "First source": "第一个源",
    "Destination": "目标",
    "Second source": "第二个源",
    "Select the primary source volume.": "选择第一个源卷。",
    "Its files determine destination names, rating selection, and the reference files used in clone mode.":
        "它的文件决定目标文件名、评分筛选以及克隆模式中使用的参考文件。",
    "Select an optional second source volume.": "选择可选的第二个源卷。",
    "Normally it is copied as another source. In clone mode, it is checked against files preserved from the first volume.":
        "通常作为另一个源进行复制。在克隆模式下，它会与从第一个卷保留的文件进行比对。",
    "Rescan mounted volumes now.": "立即重新扫描已挂载的卷。",
    "CameraCopy also refreshes the volume list automatically while idle.":
        "空闲时 CameraCopy 也会自动刷新卷列表。",
    "Open CameraCopy settings.": "打开 CameraCopy 设置。",
    "Rescan the selected volumes, validate the copy job, and start copying.":
        "重新扫描所选卷、校验复制任务并开始复制。",
    "Treat the second volume as a duplicate of the first.":
        "将第二个卷视为第一个卷的副本。",
    "CameraCopy copies from the first volume, then hash-verifies matching files on the second. Files found only on the second volume are reviewed separately.":
        "CameraCopy 从第一个卷复制，然后对第二个卷上的匹配文件做哈希校验。"
        "仅在第二个卷上找到的文件会单独处理。",
    "Remove each source file only after its destination copy has been written and successfully verified.":
        "只有在目标副本写入并成功校验之后，才会删除对应的源文件。",
    "Optionally format the selected source volume or volumes after the copy finishes successfully.":
        "可选：在复制成功完成后格式化所选的源卷。",
    "Formatting erases all remaining data on those volumes.":
        "格式化会清除这些卷上的所有剩余数据。",
    # -- common dialog titles / messages -----------------------------------
    "Settings could not be read": "无法读取设置",
    "CameraCopy could not read the settings file. The existing file has not been changed. Default settings will be used for this session.":
        "CameraCopy 无法读取设置文件。现有文件未被修改。本次会话将使用默认设置。",
    "Volume rescan failed": "卷重新扫描失败",
    "Could not rescan mounted volumes:": "无法重新扫描已挂载的卷：",
    "Could not verify the selected volumes before copying:": "复制前无法校验所选卷：",
    "No primary volume": "未选择第一个源卷",
    "Choose a primary volume first.": "请先选择第一个源卷。",
    "Duplicate volume": "卷重复",
    "Primary and secondary volume must be different.": "第一个和第二个源卷必须不同。",
    "Primary and secondary volume resolve to the same mounted volume. Choose two different volumes.":
        "第一个和第二个源卷指向同一个已挂载卷。请选择两个不同的卷。",
    "Volume unavailable": "卷不可用",
    "The selected volume is no longer mounted or available:": "所选卷已不再挂载或不可用：",
    "Use Manual rescan and try again.": "请使用“手动重新扫描”后重试。",
    "Choose destination": "选择目标位置",
    "Choose a destination folder before copying.": "复制前请先选择目标文件夹。",
    "The configured destination does not look usable on this system:":
        "配置的目标位置在此系统上似乎不可用：",
    "Choose a new folder.": "请选择新的文件夹。",
    "Choose destination folder": "选择目标文件夹",
    "Destination unavailable": "目标位置不可用",
    "Could not create or access destination folder:": "无法创建或访问目标文件夹：",
    "Destination volume will be formatted": "目标卷将被格式化",
    "The destination folder is located on a selected source volume that will be formatted after copying.":
        "目标文件夹位于一个将在复制后被格式化的所选源卷上。",
    "Formatted volume(s):": "将被格式化的卷：",
    "Choose a destination on another volume or disable formatting.":
        "请选择其他卷上的目标位置，或禁用格式化。",
    "Invalid settings": "设置无效",
    # -- copy progress dialog ----------------------------------------------
    "Copy files": "复制文件",
    "Source: —": "源：—",
    "Current file: —": "当前文件：—",
    "Current file bytes": "当前文件字节数",
    "Open destination": "打开目标位置",
    "Starting copy…": "正在开始复制…",
    "Validating source volumes…": "正在校验源卷…",
    "Formatting selected volume(s)…": "正在格式化所选卷…",
    "Finished": "已完成",
    "Finished successfully": "已成功完成",
    "Finished, but formatting failed": "已完成，但格式化失败",
    "Finished, but one or more volumes were not formatted": "已完成，但有一个或多个卷未格式化",
    "A copy problem was detected": "检测到复制问题",
    "Confirm format": "确认格式化",
    "One or more volumes were not formatted": "有一个或多个卷未格式化",
    "CameraCopy could not safely verify one or more selected volumes. No formatting command was run for those volumes.":
        "CameraCopy 无法安全校验一个或多个所选卷。未对这些卷执行任何格式化命令。",
    "Reconnect the original volume and start a new operation if you still want to format it.":
        "如果仍要格式化，请重新连接原卷并重新开始操作。",
    "This erases the selected volume.": "此操作会清除所选卷。",
    "All copy and format operations finished": "所有复制和格式化操作已完成",
    # -- collision / clone / volume mismatch dialogs -----------------------
    "Existing file": "已存在的文件",
    "Destination file already exists:": "目标文件已存在：",
    "Apply this choice for all remaining file conflicts":
        "对之后所有文件冲突都应用此选择",
    "Copy the source file under a new filename.": "以新文件名复制源文件。",
    "Replace the existing destination file with the source file.":
        "用源文件替换现有的目标文件。",
    "Leave the existing destination unchanged and skip this source file.":
        "保持现有目标不变，跳过此源文件。",
    "Stop the copy operation.": "停止复制操作。",
    "Cancel copy": "取消复制",
    "Replace existing": "替换现有",
    "Keep both": "两者都保留",
    "If you skip this file and later format the source volume, the source copy will be erased.":
        "如果跳过此文件且之后格式化源卷，源文件副本将被清除。",
    "Different files found during clone verification": "克隆校验时发现内容不同的文件",
    "Apply this choice to all remaining clone mismatches":
        "对之后所有克隆不一致都应用此选择",
    "These files have the same relative name, but their contents are different.":
        "这些文件相对名称相同，但内容不同。",
    "The destination currently contains the version copied from the first-source volume. Which version should CameraCopy preserve?":
        "目标位置当前包含从第一个源卷复制来的版本。CameraCopy 应保留哪个版本？",
    "Copied from the first-source volume:": "从第一个源卷复制：",
    "File on the second-source volume:": "第二个源卷上的文件：",
    "Existing destination file:": "已存在的目标文件：",
    "Keep the existing first-source copy and copy the second-source version under a new filename.":
        "保留现有的第一个源副本，并以新文件名复制第二个源的版本。",
    "Replace the destination file with the version from the second-source volume.":
        "用第二个源卷上的版本替换目标文件。",
    "Replace the existing destination with the second-source file.":
        "用第二个源的文件替换现有目标。",
    "Stop the copy operation. Neither volume will be formatted.":
        "停止复制操作。两个卷都不会被格式化。",
    "Remove second-source file after successful copy": "复制成功后删除第二个源的文件",
    "Apply this choice to remaining volume mismatches of this type":
        "对之后所有此类卷不一致都应用此选择",
    "Different file already exists at the destination": "目标位置已存在不同的文件",
    "File found only on the second-source volume": "仅在第二个源卷上找到的文件",
    "This file exists only on the second-source volume, but a different file already occupies its destination path.":
        "此文件仅存在于第二个源卷上，但目标路径已被另一个不同的文件占用。",
    "This file was not found on the first-source volume.":
        "此文件未在第一个源卷上找到。",
    "Copy the second-source file under a new filename and leave the existing destination unchanged.":
        "以新文件名复制第二个源的文件，保持现有目标不变。",
    "Copy the second-source file to the displayed destination.":
        "将第二个源的文件复制到所示目标位置。",
    "Size:": "大小：",
    # -- settings: tabs ----------------------------------------------------
    "Source/Destination": "源/目标",
    "Folder naming": "文件夹命名",
    "Metadata": "元数据",
    "Devices": "设备",
    "Appearance": "外观",
    "Advanced": "高级",
    # -- settings: source/destination --------------------------------------
    "Source subfolder:": "源子文件夹：",
    "Destination folder:": "目标文件夹：",
    "Source is relative to the selected volume. Use Browse to choose a folder from a mounted volume; CameraCopy stores only the relative subfolder.":
        "源路径相对于所选卷。使用“浏览”从已挂载的卷中选择文件夹；"
        "CameraCopy 仅保存相对子文件夹。",
    "Destination is where CameraCopy creates dated folders and writes copied files.":
        "目标位置是 CameraCopy 创建按日期命名的文件夹并写入复制文件的地方。",
    "Folder inside each selected source volume to scan.":
        "要扫描的、每个所选源卷内的文件夹。",
    "Leave empty to scan from the volume root. Example: DCIM.":
        "留空则从卷根目录扫描。例如：DCIM。",
    "Root folder where CameraCopy creates dated folders and writes copied files.":
        "CameraCopy 创建按日期命名的文件夹并写入复制文件的根文件夹。",
    "Choose the destination folder for copied files.":
        "选择复制文件的目标文件夹。",
    "Choose a folder on a mounted volume.": "选择一个已挂载卷上的文件夹。",
    "CameraCopy stores only its path relative to the volume.":
        "CameraCopy 仅保存其相对于卷的路径。",
    "Leave empty to copy from volume root. Example: DCIM":
        "留空则从卷根目录复制。例如：DCIM",
    "Browse…": "浏览…",
    "Choose source folder on volume": "选择卷上的源文件夹",
    # -- settings: folder naming -------------------------------------------
    "Folder tree:": "文件夹层级：",
    "Capture date only": "仅拍摄日期",
    "Today folder / capture date": "当前日期/拍摄日期",
    "Today folder only": "仅当前日期",
    "Choose how the destination folder tree is built.":
        "选择目标文件夹树的组织方式。",
    "Capture date only: one folder per capture date, as before. Today folder "
    "/ capture date: an extra folder named after the current date wraps the "
    "capture-date folders. Today folder only: every file of one copy task "
    "goes into a single folder named after the current date.":
        "仅拍摄日期：与原来一样，每个拍摄日期一个文件夹。当前日期/拍摄日期："
        "在最外层额外包一层以当前日期命名的文件夹。仅当前日期：同一次复制任务"
        "的所有文件都放进同一个以当前日期命名的文件夹。",
    "Folder prefix:": "文件夹前缀：",
    "Date format:": "日期格式：",
    "Custom date format:": "自定义日期格式：",
    "Folder postfix:": "文件夹后缀：",
    "No date folder": "不使用日期文件夹",
    "Text added before the date in each destination folder name.":
        "添加在每个目标文件夹名中日期之前的前缀文本。",
    "Text added after the date in each destination folder name.":
        "添加在每个目标文件夹名中日期之后的后缀文本。",
    "Choose how the capture date is formatted in destination folder names.":
        "选择拍摄日期在目标文件夹名中的格式。",
    "Enter a custom date pattern, such as yyyy-MM-dd.":
        "输入自定义日期格式，例如 yyyy-MM-dd。",
    "Used only when Custom is selected.": "仅在选择“自定义”时使用。",
    "Common date presets are shown as examples. Custom formats use the CameraCopy date format, for example yyyy-MM-dd.":
        "常见日期预设仅作示例。自定义格式使用 CameraCopy 日期格式，例如 yyyy-MM-dd。",
    "Preview unavailable:": "无法预览：",
    "Source example:": "源示例：",
    "Destination example:": "目标示例：",
    "Source example": "源示例",
    "Destination example": "目标示例",
    # -- settings: metadata ------------------------------------------------
    "Minimum rating:": "最低评分：",
    "Sony MP4 timestamps:": "Sony MP4 时间戳：",
    "Embedded metadata:": "内嵌元数据：",
    "External metadata tool:": "外部元数据工具：",
    "Diagnostics:": "诊断：",
    "Off": "关闭",
    "1 star and up": "1 星及以上",
    "2 stars and up": "2 星及以上",
    "3 stars and up": "3 星及以上",
    "4 stars and up": "4 星及以上",
    "5 stars only": "仅 5 星",
    "Use Sony XML timestamps for Sony MP4 files": "对 Sony MP4 文件使用 Sony XML 时间戳",
    "Use capture timestamps from matching Sony XML files when determining destination folders for Sony MP4 videos.":
        "在为 Sony MP4 视频确定目标文件夹时，使用匹配的 Sony XML 文件中的拍摄时间戳。",
    "Use embedded metadata through ExifTool during copy": "复制时通过 ExifTool 使用内嵌元数据",
    "Allow ExifTool to read embedded ratings and capture timestamps when suitable sidecar metadata is unavailable.":
        "当没有合适的附属文件元数据时，允许 ExifTool 读取内嵌评分和拍摄时间。",
    "This can slow large copy jobs.": "这会减慢大型复制任务。",
    "Copy only files whose rating meets or exceeds this value.":
        "仅复制评分达到或高于此值的文件。",
    "CameraCopy reads ratings from supported Adobe XMP and .rrdata sidecars. Embedded ratings can also be read through ExifTool. Other sidecar formats are not guaranteed to be supported. Files without a readable rating are treated as 0.":
        "CameraCopy 从受支持的 Adobe XMP 和 .rrdata 附属文件读取评分。"
        "也可通过 ExifTool 读取内嵌评分。其他附属文件格式不保证受支持。"
        "没有可读评分的文件按 0 处理。",
    "CameraCopy reads supported Adobe XMP and .rrdata sidecars, and embedded metadata when ExifTool reading is enabled. Other sidecar formats are not guaranteed to be supported. Files without a rating are treated as 0.":
        "CameraCopy 读取受支持的 Adobe XMP 和 .rrdata 附属文件，"
        "并在启用 ExifTool 读取时读取内嵌元数据。其他附属文件格式不保证受支持。"
        "没有评分的文件按 0 处理。",
    "Shows whether ExifTool is available for embedded metadata reading and diagnostics.":
        "显示 ExifTool 是否可用于内嵌元数据读取和诊断。",
    "ExifTool was not found. Embedded ratings cannot be read. CameraCopy will only use supported Adobe XMP and .rrdata sidecar ratings. Files without a supported rating sidecar will be treated as unrated.":
        "未找到 ExifTool。无法读取内嵌评分。CameraCopy 将仅使用受支持的 "
        "Adobe XMP 和 .rrdata 附属文件评分。没有受支持评分附属文件的文件将视为未评分。",
    "Run metadata diagnostics": "运行元数据诊断",
    "Select one or more files and inspect their metadata using ExifTool.":
        "选择一个或多个文件，用 ExifTool 检查其元数据。",
    "CameraCopy displays all metadata ExifTool can read, together with the timestamp candidates and folder date CameraCopy would choose. Files and settings are not changed.":
        "CameraCopy 会显示 ExifTool 能读取的所有元数据，以及时间戳候选项和 "
        "CameraCopy 将选择的文件夹日期。文件和设置不会被更改。",
    "Metadata diagnostics": "元数据诊断",
    "Choose files for metadata diagnostics": "选择用于元数据诊断的文件",
    # -- settings: files ---------------------------------------------------
    "Pattern preset:": "规则预设：",
    "Apply preset": "应用预设",
    "Common camera media": "常见相机媒体",
    "Everything": "全部",
    "Include:": "包含：",
    "Exclude:": "排除：",
    "Choose a predefined set of include and exclude patterns.":
        "选择一组预定义的文件包含/排除规则。",
    "The lists are not changed until Apply preset is pressed.":
        "在按下“应用预设”之前，列表不会改变。",
    "Replace the current include and exclude patterns with the selected preset.":
        "用所选预设替换当前的包含和排除规则。",
    "Select files that match at least one of these patterns.":
        "选择至少匹配其中一个规则的文件。",
    "Use patterns such as *.ARW or *.JPG.": "使用诸如 *.ARW 或 *.JPG 的规则。",
    "Ignore files that match any of these patterns, even when they also match an include pattern.":
        "忽略匹配其中任一规则的文件，即使它们也匹配某个包含规则。",
    "Verification:": "校验：",
    "Sidecars:": "附属文件：",
    "Existing files:": "已存在的文件：",
    "Source cleanup:": "源文件清理：",
    "Verify copied files against the source": "校验复制文件是否与源一致",
    "Hash method:": "哈希算法：",
    "Verify timing:": "校验时机：",
    "SHA-256 — universally compatible": "SHA-256 — 通用性最强，可外部复核",
    "xxHash64 — fastest, non-cryptographic": "xxHash64 — 速度最快，非加密哈希",
    "Each file right after it is copied": "逐个文件（拷贝完立即校验）",
    "All files after the whole batch": "整组任务完成后统一校验",
    "SHA-256: most compatible — any tool can re-check it, which suits long-term archives; slower because it is CPU-bound.\nxxHash64: fastest — several times quicker on large cards; non-cryptographic, so fewer external tools support it.":
        "SHA-256：通用性最强 —— 任何工具都能复核校验值，适合长期归档；"
        "速度较慢（受 CPU 限制）。\n"
        "xxHash64：速度最快 —— 大容量卡上可快数倍；属于非加密哈希，"
        "支持它的外部工具较少。",
    "The optional xxhash acceleration module is not installed, so xxHash64 will run as a pure-Python fallback that is much slower than SHA-256. Install it with: pip install xxhash":
        "未检测到可选的 xxhash 加速模块，xxHash64 将以纯 Python 实现运行，"
        "速度会远低于 SHA-256。建议执行：pip install xxhash",
    "Each file right after it is copied: a file that fails its check never reaches the destination, and the problem is reported while that file is still on screen.":
        "逐个文件（拷贝完立即校验）：未通过校验的文件不会落到目标位置，"
        "问题会在该文件仍在处理时立即报出。",
    "All files after the whole batch: copying runs uninterrupted and throughput is smoother on slow media, but problems surface later. With source removal enabled, files are deleted only after every check has passed.":
        "整组任务完成后统一校验：写入阶段不被打断，慢速介质上的整体吞吐更平稳，"
        "但发现问题较晚。若启用源文件删除，删除会等到全部校验通过后才执行。",
    "Choose the hash algorithm used for verification.": "选择用于校验的哈希算法。",
    "SHA-256 is the most compatible choice and can be re-checked with external tools. xxHash64 is much faster but is not a cryptographic hash.":
        "SHA-256 兼容性最好，可以用外部工具复核。"
        "xxHash64 快得多，但不是加密哈希。",
    "Choose when destination files are hashed.": "选择对目标文件计算哈希的时机。",
    "Each file verifies as soon as it is written. All files defers every check until the copy has finished, which keeps writing uninterrupted.":
        "「逐个文件」在每个文件写完时立即校验；「整组任务」把全部校验推迟到拷贝"
        "结束之后，写入过程不被打断。",
    "Compare a hash of the source and destination after copying.":
        "复制后比较源与目标的哈希值。",
    "When disabled, normal copies use a basic size check. Clone verification always hashes the compared files.":
        "禁用时，普通复制使用基本的体积检查。克隆校验始终会对比较的文件计算哈希。",
    "Batch verification": "统一校验",
    "Verifying file": "正在校验文件",
    "Copy matching sidecars (.xmp, .rrdata)": "复制匹配的附属文件（.xmp、.rrdata）",
    "Skip existing files": "跳过已存在的文件",
    "Always ask": "总是询问",
    "Replace existing files": "替换已存在的文件",
    "Copy matching XMP and RapidRaw sidecars for selected media files.":
        "为选中的媒体文件复制匹配的 XMP 和 RapidRaw 附属文件。",
    "Ratings can still be read from sidecars when this option is disabled.":
        "禁用此选项时仍可从附属文件读取评分。",
    "Set the default source-removal choice shown on the main screen.":
        "设置主界面上默认的源文件删除选项。",
    "Verification is disabled. CameraCopy will not confirm that copied file contents match the source. Source removal and formatting will have reduced protection.":
        "校验已禁用。CameraCopy 不会确认复制文件的内容与源一致。"
        "源文件删除和格式化将失去部分保护。",
    "Copied after confirmation:": "确认后复制：",
    "Successful copy:": "复制成功：",
    "Information:": "信息：",
    # -- settings: devices -------------------------------------------------
    "Volume filter keywords:": "卷筛选关键词：",
    "Default primary volume:": "默认第一个源卷：",
    "Default secondary volume:": "默认第二个源卷：",
    "Match primary volume by:": "匹配第一个源卷依据：",
    "Match secondary volume by:": "匹配第二个源卷依据：",
    "None — no default primary volume": "（无）— 无默认第一个源卷",
    "None — no default secondary volume": "（无）— 无默认第二个源卷",
    "Leave empty to show all mounted volumes.": "留空则显示所有已挂载的卷。",
    "Show a volume when any keyword appears in its name, label, model, mount path, filesystem, or device identifiers.":
        "当任一关键词出现在卷的名称、标签、型号、挂载路径、文件系统或设备标识中时，显示该卷。",
    "Automatically select this volume as the first source when CameraCopy finds a match.":
        "当 CameraCopy 找到匹配项时，自动将此卷选为第一个源。",
    "Automatically select this volume as the second source when CameraCopy finds a match.":
        "当 CameraCopy 找到匹配项时，自动将此卷选为第二个源。",
    "Choose which volume property CameraCopy uses to recognize the default primary volume after remounting or formatting.":
        "选择 CameraCopy 在重新挂载或格式化后用于识别默认第一个源卷的卷属性。",
    "Choose which volume property CameraCopy uses to recognize the default secondary volume after remounting or formatting.":
        "选择 CameraCopy 在重新挂载或格式化后用于识别默认第二个源卷的卷属性。",
    "Leave filters empty to show all mounted volumes. Default volumes are stored with an explicit matching rule such as Device serial, Filesystem UUID, Size, or Mount point. Device serial is usually the best choice for frequently formatted volumes when the camera exposes unique serials.":
        "筛选留空则显示所有已挂载的卷。默认卷会以明确的匹配规则保存，"
        "例如设备序列号、文件系统 UUID、容量或挂载点。"
        "对于经常格式化的卷，当相机提供唯一序列号时，设备序列号通常是首选。",
    # -- settings: appearance ----------------------------------------------
    "Theme:": "主题：",
    "Follow system theme": "跟随系统主题",
    "Light": "浅色",
    "Dark": "深色",
    "Choose the application appearance or follow the operating-system theme.":
        "选择应用外观，或跟随操作系统主题。",
    "Choose the language used by the CameraCopy interface.":
        "选择 CameraCopy 界面使用的语言。",
    "Copy behavior": "复制行为",
    "Copy log colors": "复制日志配色",
    "Background:": "背景色：",
    "Background color of the copy log.": "复制日志的背景色。",
    "Reset all colors to automatic": "将所有颜色重置为自动",
    "Return every copy-log color to its automatic theme-derived value.":
        "将所有复制日志颜色恢复为主题自动派生值。",
    "Return this color to the automatic value derived from the selected theme.":
        "将此颜色恢复为所选主题的自动派生值。",
    "Choose copy log color": "选择复制日志颜色",
    # -- settings: advanced ------------------------------------------------
    "Format requirements:": "格式化要求：",
    "Default format choice:": "默认格式选择：",
    "Format confirmation:": "格式化确认：",
    "Durable writes:": "持久写入：",
    "Ask before formatting": "格式化前询问",
    "Flush copied files to disk after writing": "写入后将复制文件刷写到磁盘",
    "Check format requirements": "检查格式化要求",
    "Format requirements": "格式化要求",
    "Detected formatting tools and services:": "检测到的格式化工具和服务：",
    "Set the filesystem offered by default for formatting after a successful copy.":
        "设置复制成功后格式化时默认提供的文件系统。",
    "Show whether the tools and services required for each supported filesystem are available.":
        "显示每个受支持文件系统所需的工具和服务是否可用。",
    "Formatting erases the selected source volumes.": "格式化会清除所选的源卷。",
    "Formatting erases the volume. CameraCopy blocks formatting if the copy job fails or is cancelled. Disabling the format prompt is dangerous and should only be used in a controlled workflow.":
        "格式化会清除该卷。如果复制任务失败或被取消，CameraCopy 会阻止格式化。"
        "禁用格式化提示很危险，仅应在受控流程中使用。",
    "Require a final confirmation before each source volume is formatted.":
        "在每个源卷格式化前要求最终确认。",
    "Disabling this removes an important safety check.": "禁用此项会移除一项重要的安全检查。",
    "Durable writes are disabled. Copying may finish before all data has been committed to the destination device. Source removal and formatting will have reduced protection.":
        "持久写入已禁用。复制可能在所有数据写入目标设备之前就完成。"
        "源文件删除和格式化将失去部分保护。",
    "Flush each copied file to storage before verification and request a destination-folder flush after renaming.":
        "在校验前将每个复制文件刷写到存储，并在重命名后请求刷写目标文件夹。",
    "This is slower but more conservative.": "这会更慢，但更保守。",
    "Open destination in application": "在应用程序中打开目标位置",
    "Application name:": "应用程序名称：",
    "Path to application:": "应用程序路径：",
    "Environment variables:": "环境变量：",
    "Command-line arguments:": "命令行参数：",
    "Example launch:": "启动示例：",
    "Choose application executable": "选择应用程序可执行文件",
    "Choose the application executable CameraCopy should launch.":
        "选择 CameraCopy 要启动的应用程序可执行文件。",
    "CameraCopy launches the application directly without a command shell.":
        "CameraCopy 直接启动应用程序，不使用命令行外壳。",
    "Select the executable CameraCopy should launch.": "选择 CameraCopy 要启动的可执行文件。",
    "Name shown on the completion-dialog button.": "完成对话框按钮上显示的名称。",
    "Both an application name and application path are required before the button is shown.":
        "需要同时填写应用程序名称和路径，才会显示该按钮。",
    "Both an application path and application name are required before the completion-dialog button is shown.":
        "需要同时填写应用程序路径和名称，才会在完成对话框中显示该按钮。",
    "Shows the executable, environment variables, and arguments CameraCopy will use with the currently configured destination.":
        "显示在当前配置的目标位置下，CameraCopy 将使用的可执行文件、环境变量和参数。",
    "Optional environment variables supplied only to the launched application.":
        "仅提供给所启动应用程序的可选环境变量。",
    "Enter space-separated NAME=value assignments. Quote values containing spaces, for example CACHE_PATH=\"/path with spaces\".":
        "输入以空格分隔的 名称=值 赋值。包含空格的值请加引号，"
        "例如 CACHE_PATH=\"/path with spaces\"。",
    "Optional arguments passed to the application. Use %d wherever the destination directory should be inserted.":
        "传递给应用程序的可选参数。在需要插入目标目录的位置使用 %d。",
    "Leave this field empty, or omit %d, to launch the application without passing the destination directory.":
        "将此字段留空，或省略 %d，将在不传入目标目录的情况下启动应用程序。",
    "Use %d in command-line arguments to pass the destination directory. Leave the arguments empty, or omit %d, to launch the application without giving it a directory. The completion button is shown only when both an application name and path are configured.":
        "在命令行参数中使用 %d 传入目标目录。将参数留空，或省略 %d，"
        "将在不给定目录的情况下启动应用程序。仅当同时配置了应用程序名称和路径时，"
        "才会显示完成按钮。",
    "Save these default volume matching settings anyway?": "仍要保存这些默认卷匹配设置吗？",
    # -- log statuses (structured copy results) ----------------------------
    "COPIED": "已复制",
    "REPLACED": "已替换",
    "RENAMED COPY": "重命名副本",
    "VERIFIED EXISTING": "已验证现有文件",
    "SKIPPED": "已跳过",
    "FAILED": "失败",
    "CLONE VERIFIED": "克隆校验通过",
    "CLONE FAILED": "克隆失败",
    "CLONE MISMATCH — KEPT BOTH": "克隆不一致 — 两者都保留",
    "CLONE MISMATCH — USED SECOND-SOURCE": "克隆不一致 — 采用第二个源",
    "CLONE MISMATCH — KEPT FIRST-SOURCE": "克隆不一致 — 保留第一个源",
    "VOLUME MISMATCH — COPIED": "卷不一致 — 已复制",
    "VOLUME MISMATCH — KEPT BOTH": "卷不一致 — 两者都保留",
    "VOLUME MISMATCH — REPLACED": "卷不一致 — 已替换",
    "VOLUME MISMATCH — KEPT EXISTING": "卷不一致 — 保留现有",
    "VOLUME MISMATCH — FOUND IDENTICAL COPY IN DESTINATION": "卷不一致 — 在目标中找到相同副本",
    "VOLUME MISMATCH — SKIPPED": "卷不一致 — 已跳过",
    "FORMATTING FINISHED SUCCESSFULLY.": "格式化已成功完成。",
    "FORMATTING FINISHED WITH FAILURE": "格式化以失败结束",
    "FORMATTING CANCELLED": "格式化已取消",
    "FORMATTING SKIPPED": "已跳过格式化",
    "FORMATTING WORKER FAILED": "格式化工作线程失败",
    "STATUS: FINISHED SUCCESSFULLY": "状态：已成功完成",
    "STATUS: FINISHED WITH FAILURES": "状态：已完成但有失败项",
    "STATUS: CANCELLED": "状态：已取消",
    "INTERNAL ERROR": "内部错误",
    # -- log details -------------------------------------------------------
    "Second-source file": "第二个源文件",
    "Existing destination": "已存在的目标",
    "First-source copy remains": "第一个源副本保留",
    "First-source copy replaced": "第一个源副本已替换",
    "Second-source copied": "第二个源已复制",
    "Second-source not copied": "第二个源未复制",
    "destination exists; user chose skip": "目标已存在；用户选择跳过",
    "destination exists and overwrite is disabled": "目标已存在且未启用覆盖",
    "volume mismatch; user chose skip": "卷不一致；用户选择跳过",
    "volume mismatch; user kept existing destination": "卷不一致；用户保留了现有目标",
    "clone mismatch; user kept first-source version": "克隆不一致；用户保留了第一个源的版本",
    "selected on the first-source volume, not found on the second-source volume":
        "在第一个源卷上被选中，但在第二个源卷上未找到",
    "SHA256 FAILED": "SHA256 校验失败",
    "verification failed": "校验失败",
    "Copy report": "复制报告",
    "Copy worker starting": "复制工作线程正在启动",
    "Pre-copy scan requested": "已请求复制前扫描",
    "Pre-copy validation completed successfully": "复制前校验已成功完成",
    "Pre-copy volume scan failed": "复制前卷扫描失败",
    "Pre-copy identity validation failed for": "以下项的复制前身份校验失败",
    "Pre-copy identity validation found the same mounted volume in both roles":
        "复制前身份校验发现两个角色指向同一个已挂载卷",
    "Copy validation failed: no primary volume selected": "复制校验失败：未选择第一个源卷",
    "Copy validation stopped: destination is unavailable": "复制校验已停止：目标位置不可用",
    "Copy validation failed: primary and secondary point to the same mounted volume":
        "复制校验失败：第一个和第二个源指向同一个已挂载卷",
    "Copy validation failed: destination is on a volume selected for formatting":
        "复制校验失败：目标位置位于被选中要格式化的卷上",
    "Copy cancelled while source-volume validation was pending":
        "在源卷校验进行中时取消了复制",
    "Application closed while pre-copy validation was pending":
        "在复制前校验进行中时关闭了应用",
    "Could not kill ExifTool cleanly:": "无法干净地结束 ExifTool：",
    "Could not terminate ExifTool cleanly:": "无法干净地终止 ExifTool：",
    "ExifTool metadata read timed out for": "ExifTool 元数据读取超时：",
    "ExifTool exited with code": "ExifTool 退出，代码",
    "Could not remove CameraCopy temporary file": "无法删除 CameraCopy 临时文件",
    # -- diagnostics report ------------------------------------------------
    "No files selected.": "未选择文件。",
    "File modified time:": "文件修改时间：",
    "Filesystem created time:": "文件系统创建时间：",
    "Sony XML timestamp:": "Sony XML 时间戳：",
    "Embedded metadata time:": "内嵌元数据时间：",
    "XMP sidecar time:": "XMP 附属文件时间：",
    "Chosen folder date:": "选定的文件夹日期：",
    "Chosen source:": "选定来源：",
    "ExifTool metadata:": "ExifTool 元数据：",
    "ExifTool status": "ExifTool 状态",
    "file modified time": "文件修改时间",
    "embedded metadata": "内嵌元数据",
    "XMP sidecar": "XMP 附属文件",
    "Sony XML": "Sony XML",
    # -- copy log colour descriptions --------------------------------------
    "Color used for routine progress and configuration messages.":
        "用于常规进度和配置信息的颜色。",
    "Color used for successful copies and verification results that required no user decision.":
        "用于成功复制以及无需用户决定即通过的校验结果的颜色。",
    "Color used for successful actions performed after a conflict or mismatch decision.":
        "用于在冲突或不一致决定之后执行的成功操作的颜色。",
    "Color used for mismatches, intentional omissions, and other nonfatal safety conditions.":
        "用于不一致、有意省略以及其他非致命安全状况的颜色。",
    "Color used for failed copies, failed verification, formatting failures, and internal errors.":
        "用于失败复制、校验失败、格式化失败和内部错误的颜色。",
    # -- copy log preview samples ------------------------------------------
    "Scanning first-source volume…": "正在扫描第一个源卷…",
    "VOLUME MISMATCH:": "卷不一致：",
    "CLONE MISMATCH:": "克隆不一致：",
    "FORMAT SKIPPED:": "已跳过格式化：",
    "FORMAT FAILED:": "格式化失败：",
    "VOLUME MISMATCH — KEPT EXISTING:": "卷不一致 — 保留现有：",
    "VOLUME MISMATCH — SKIPPED:": "卷不一致 — 已跳过：",
    "VOLUME MISMATCH — COPIED:": "卷不一致 — 已复制：",
    "VOLUME MISMATCH — KEPT BOTH:": "卷不一致 — 两者都保留：",
    "VOLUME MISMATCH — REPLACED:": "卷不一致 — 已替换：",
    "VOLUME MISMATCH — FOUND IDENTICAL COPY IN DESTINATION:": "卷不一致 — 在目标中找到相同副本：",
    "CLONE MISMATCH — KEPT BOTH:": "克隆不一致 — 两者都保留：",
    "CLONE MISMATCH — KEPT FIRST-SOURCE:": "克隆不一致 — 保留第一个源：",
    "CLONE MISMATCH — USED SECOND-SOURCE:": "克隆不一致 — 采用第二个源：",
    "RENAMED COPY:": "重命名副本：",
    "REPLACED:": "已替换：",
    "COPIED:": "已复制：",
    "SKIPPED:": "已跳过：",
    "FAILED:": "失败：",
    "CLONE FAILED:": "克隆失败：",
    "CLONE VERIFIED:": "克隆校验通过：",
    "VERIFIED EXISTING:": "已验证现有文件：",
    # -- format service ----------------------------------------------------
    "PowerShell was not found.": "未找到 PowerShell。",
    "WMI support was not found; removable-drive detection is unavailable.":
        "未找到 WMI 支持；无法检测可移动驱动器。",
    "Install exfatprogs.": "请安装 exfatprogs。",
    "Install dosfstools.": "请安装 dosfstools。",
    "Install e2fsprogs.": "请安装 e2fsprogs。",
    # -- copy-engine log labels -------------------------------------------
    "Verification": "校验方式",
    "Clone verification": "克隆校验方式",
    "Minimum rating": "最低星级",
    "Existing files": "已存在文件",
    "Sidecars": "附属文件",
    "Source cleanup": "源文件清理",
    "Copy session": "复制会话",
    "Resumed session": "已恢复的会话",
    "Status": "状态",
    "Ratings": "星级统计",
    "Bytes written": "已写入字节",
    "Copy time": "复制耗时",
    "Average write speed": "平均写入速度",
    "Redundant bytes written": "冗余备份写入字节",
    "Batch verification time": "统一校验耗时",
    "Starting file copy": "开始复制文件",
    "Starting second-source file copy": "开始复制第二个源的文件",
    "do not copy": "不复制",
    "copy matching XMP and RapidRaw files": "复制匹配的 XMP 与 RapidRaw 文件",
    "leave source files in place": "保留源文件",
    "remove after successful copy": "复制成功后删除",
    "finished with failures": "已完成，但有失败项",
    "finished successfully": "已成功完成",
    "basic size check": "仅基础大小校验",
    "each file right after it is copied": "每个文件复制完成后立即校验",
    "all copied files after the batch finishes": "全部复制完成后再统一校验",
    "SHA256 (each file right after it is copied)":
        "SHA256（每个文件复制完成后立即校验）",
    "xxHash64 (each file right after it is copied)":
        "xxHash64（每个文件复制完成后立即校验）",
    "SHA256 (all copied files after the batch finishes)":
        "SHA256（全部复制完成后再统一校验）",
    "xxHash64 (all copied files after the batch finishes)":
        "xxHash64（全部复制完成后再统一校验）",
    "Batch verification cancelled.": "统一校验已取消。",
    "nothing to verify.": "没有需要校验的文件。",
    "source removal failed": "删除源文件失败",
    "destination does not match the source": "目标文件与源文件内容不一致",
    # -- copy summary counters --------------------------------------------
    "Starting file copy...": "开始复制文件…",
    "Starting second-source file copy...": "开始复制第二个源的文件…",
    "Redundant backups": "冗余备份",
    "total": "总计",
    "copied": "已复制",
    "new": "新增",
    "kept both": "两者都保留",
    "replaced": "已替换",
    "verified existing": "已校验的现有文件",
    "verified clones": "已校验的克隆",
    "skipped": "已跳过",
    "failed": "失败",
    "source files removed": "个源文件已删除",
    "already copied by an earlier run": "个文件在之前的运行中已复制",
    "continued from partial files": "个文件为断点续传",
    "FORMATTED": "已格式化",
    "RapidRaw sidecar": "RapidRaw 附属文件",
    "Embedded metadata": "内嵌元数据",
    "No rating found (treated as 0)": "未找到星级（按 0 处理）",
    # -- interrupted-copy recovery ----------------------------------------
    "Resume interrupted copy": "继续中断的复制",
    "Discard session": "放弃该会话",
    "Resume interrupted file copies": "继续中断的文件复制",
    "Interrupted files:": "中断的文件：",
    "Interrupted copies:": "中断的复制：",
    "CameraCopy records which source files have already been preserved. After a cancelled copy, a crash, or a power failure it can rebuild the same job and continue with the remaining files. The record is stored outside the destination folder and is deleted as soon as the copy finishes successfully.":
        "CameraCopy 会记录哪些源文件已经保存完成。若复制被取消、程序崩溃或断电，"
        "它可以重建同一个任务并继续复制剩余文件。该记录保存在目标文件夹之外，"
        "复制成功完成后会立即删除。",
    # -- interrupted-copy recovery: dialogs and log lines ------------------
    "Interrupted copy": "中断的复制",
    "Discard interrupted copy": "放弃中断的复制",
    "Recover interrupted copy jobs": "恢复中断的复制任务",
    "Resuming interrupted copy…": "正在继续中断的复制…",
    "Continue the interrupted copy that matches the connected volumes.":
        "继续与当前已连接卷匹配的中断复制。",
    "CameraCopy reuses the settings of the interrupted run and skips the files it already copied.":
        "CameraCopy 会沿用中断那次的设置，并跳过已经复制完成的文件。",
    "Delete the saved copy session and its partially copied files.":
        "删除保存的复制会话及其尚未写完的部分文件。",
    "The files that were already copied to the destination are kept.":
        "已经复制到目标的文件会保留。",
    "The saved settings of the interrupted copy could not be read, so it cannot be resumed. Start a new copy instead.":
        "无法读取中断复制保存的设置，因此无法继续。请改为开始新的复制。",
    "The destination folder of the interrupted copy is not available:":
        "中断复制的目标文件夹不可用：",
    "Reconnect it and try again, or start a new copy.":
        "请重新连接后重试，或开始新的复制。",
    "Delete the saved state of the interrupted copy?": "要删除中断复制的保存状态吗？",
    "Files already copied by that run": "该次运行已复制的文件",
    "Files already copied": "已复制的文件",
    "Files that were already copied to the destination are kept. Only the recovery information and unfinished partial files are removed.":
        "已经复制到目标的文件会保留，只会删除恢复信息和尚未写完的部分文件。",
    "Continue a file that an interrupted copy already started.":
        "继续复制上次中断时已经开始的文件。",
    "CameraCopy keeps the partially written data in the destination and continues it on the next attempt instead of transferring the whole file again. A partial file is only continued when it still belongs to the exact source file it was copied from.":
        "CameraCopy 会在目标中保留已经写入的部分数据，下次尝试时从断点继续，"
        "而不必重新传输整个文件。只有当部分文件仍然属于它原本的来源文件时才会继续。",
    "Save the state of a running copy so it can be continued later.":
        "保存正在进行的复制状态，以便之后继续。",
    "Nothing is written to the source or destination volumes; the record only lists the files that have already been preserved.":
        "不会向源卷或目标卷写入任何内容；该记录只列出已经保存完成的文件。",
    "The interrupted copy is saved and can be resumed later.":
        "中断的复制已保存，之后可以继续。",
    "Interrupted copies can be resumed from the saved session.":
        "中断的复制可以从保存的会话继续。",
    "Interrupted copies of this job can be resumed while it runs.":
        "本次任务在运行期间即可从保存的会话继续。",
    "Copy session finished; nothing is left to resume.":
        "复制会话已完成，没有需要继续的内容。",
    "Interrupted copy stopped; it can be resumed later.":
        "中断的复制已停止，之后可以继续。",
    "Bytes continued from partial files": "断点续传已写入的字节",
    # ------------------------------------------------------------------
    # Metadata-based file renaming (main window + Naming and metadata tab)
    # ------------------------------------------------------------------
    "Rename files from metadata": "根据元数据重命名文件",
    "File renaming:": "文件重命名：",
    "File renaming": "文件重命名",
    "Rating and metadata": "评分与元数据",
    "Naming and metadata": "命名与元数据",
    "File prefix:": "文件前缀：",
    "File postfix:": "文件后缀：",
    "Date source:": "日期来源：",
    "File name pattern:": "文件名通配模式：",
    "No date": "不含日期",
    "Same as folder date": "与文件夹日期相同",
    "EXIF DateTimeOriginal": "EXIF DateTimeOriginal（拍摄时间）",
    "EXIF CreateDate": "EXIF CreateDate（创建时间）",
    "QuickTime CreateDate": "QuickTime CreateDate（创建时间）",
    "XMP CreateDate": "XMP CreateDate（创建时间）",
    "File modified time": "文件修改时间",
    "Rename copied files from their capture metadata.":
        "根据拍摄元数据重命名复制后的文件。",
    "Configure the naming rules in Settings on the Naming and metadata tab.":
        "命名规则请在「设置」的「命名与元数据」页中配置。",
    "Text added before the date in each renamed file name.":
        "添加在每个重命名文件名中日期之前的文字。",
    "Text added after the date in each renamed file name.":
        "添加在每个重命名文件名中日期之后的文字。",
    "Only used while the pattern is left empty.": "仅在通配模式留空时使用。",
    "Which date the renamed file name is built from.":
        "重命名后的文件名使用哪个日期。",
    "Pick a specific EXIF, QuickTime or XMP field, keep the folder date, or use "
    "the file modified time. When the chosen field is missing, CameraCopy falls "
    "back to the folder date so the file is still renamed.":
        "可选择具体的 EXIF、QuickTime 或 XMP 字段，沿用文件夹日期，或使用文件修改时间。"
        "所选字段缺失时，CameraCopy 会退回文件夹日期，文件仍会被重命名。",
    "Choose how the date is formatted in renamed file names.":
        "选择重命名文件名中日期的格式。",
    "Enter a custom date pattern, such as yyyyMMdd_HHmmss.":
        "输入自定义日期格式，例如 yyyyMMdd_HHmmss。",
    "Rebuild the whole file name from tokens.":
        "用占位符重新组合整个文件名。",
    "Working with the pattern replaces prefix and postfix. Example: "
    "{date}-{name} turns DJI0001.MP4 into 20260101-DJI0001.MP4.":
        "填写通配模式后将忽略前缀和后缀。例：{date}-{name} 会把 "
        "DJI0001.MP4 重命名为 20260101-DJI0001.MP4。",
    # File stem validation messages (mirrors the folder-name wording)
    "File name contains characters that are invalid on Windows.":
        "文件名包含 Windows 不允许的字符。",
    "File name must not end with a space or period on Windows.":
        "文件名在 Windows 上不能以空格或句点结尾。",
    "File name is reserved by Windows.": "文件名是 Windows 保留名。",
    "The rename pattern produced an empty file name.": "重命名模式生成了空文件名。",
}


# ---------------------------------------------------------------------------
# Pattern rules for strings that contain dynamic values
# ---------------------------------------------------------------------------

RuleFn = Callable[[re.Match[str]], str]


def _label_rule(match: re.Match[str]) -> str:
    """``Foo: <value>`` -> translate the label (and a known value)."""
    label = match.group(1)
    zh = TRANSLATIONS.get(label)
    if zh is None:
        return match.group(0)
    value = match.group(2)
    return f"{zh}：{TRANSLATIONS.get(value, value)}"


def _ellipsis_rule(match: re.Match[str]) -> str:
    """``Foo: Bar...`` -> translate the known parts and use an ellipsis."""
    head, tail = match.group(1), match.group(2)
    head_zh = TRANSLATIONS.get(head)
    tail_zh = TRANSLATIONS.get(tail)
    if head_zh is None and tail_zh is None:
        return match.group(0)
    return f"{head_zh or head}：{tail_zh or tail}…"


def _trailing_colon_rule(match: re.Match[str]) -> str:
    inner = match.group(1)
    zh = TRANSLATIONS.get(inner) or TRANSLATIONS.get(inner.lower())
    if zh is None:
        return match.group(0)
    return f"{zh}："


def _uppercase_status_rule(match: re.Match[str]) -> str:
    code = match.group(1)
    zh = TRANSLATIONS.get(code)
    if zh is None:
        return match.group(0)
    tail = match.group(2)
    return zh + ("：" + tail if tail else "")


def _size_paren_rule(match: re.Match[str]) -> str:
    return f"（{match.group(1)}）"


def _translate_reason(reason: str) -> str:
    """Translate a short reason string without re-entering the paren rule."""
    exact = TRANSLATIONS.get(reason)
    if exact is not None:
        return exact
    for pattern, rule in _PATTERNS:
        source = pattern.pattern
        if source.startswith(r"^(.+) \(unavailable"):
            continue
        if pattern.match(reason):
            try:
                result = rule(pattern.match(reason))  # type: ignore[arg-type]
            except Exception:  # pragma: no cover
                continue
            if result and result != reason:
                return result
    return reason


def _em_dash_rule(match: re.Match[str]) -> str:
    left, right = match.group(1), match.group(2)
    left_zh = TRANSLATIONS.get(left)
    right_zh = TRANSLATIONS.get(right)
    if left_zh is None and right_zh is None:
        return match.group(0)
    return f"{left_zh or left} — {right_zh or right}"


_PATTERN_SOURCES: list[tuple[str, RuleFn]] = [
    # availability reason shown inside a combo box entry
    (
        r"^(.+) \(unavailable: (.+)\)$",
        lambda m: f"{m.group(1)}（不可用：{_translate_reason(m.group(2))}）",
    ),
    # placeholder examples
    (r"^Example: (.+)$", lambda m: f"例如：{m.group(1)}"),
    # "Finished with N failure(s)"
    (
        r"^Finished with (.+) failure\(s\)$",
        lambda m: f"已完成，{m.group(1)} 项失败",
    ),
    # combined status such as "COPIED + REMOVED: src -> dst"
    (
        r"^([A-Z][A-Z0-9 —\-]{2,40}) \+ REMOVED: (.*)$",
        lambda m: (
            f"{TRANSLATIONS.get(m.group(1), m.group(1))} + 已删除：{m.group(2)}"
        ),
    ),
    # summary counters such as "2 copied" / "1 source files removed"
    (
        r"^(\d[\d,]*) ([a-z][a-z /]*)$",
        lambda m: f"{m.group(1)} {TRANSLATIONS.get(m.group(2), m.group(2))}",
    ),
    # "Copy time: 0.4 seconds" — translate the unit as well as the label
    (
        r"^([A-Za-z][A-Za-z0-9 /&'’.,\-]*?): ([0-9][0-9.,]*) seconds?$",
        lambda m: f"{TRANSLATIONS.get(m.group(1), m.group(1))}：{m.group(2)} 秒",
    ),
    # "Label: Value" where the label is a known string
    (r"^([A-Za-z][A-Za-z0-9 /&'’.,\-]*?): (.*)$", _label_rule),
    # numbered source progress, e.g. "Source 1/2: Copying..."
    (
        r"^Source (\d+/\d+): (.*)$",
        lambda m: f"源 {m.group(1)}：{TRANSLATIONS.get(m.group(2), m.group(2))}",
    ),
    # progress style "Label: Value..."
    (r"^([A-Za-z][A-Za-z0-9 /&'’.,\-]*?): (.+)\.\.\.$", _ellipsis_rule),
    # uppercase status lines produced by the copy engine
    (r"^([A-Z][A-Z0-9 —\-]{2,60}): (.*)$", _uppercase_status_rule),
    (r"^([A-Z][A-Z0-9 —\-]{2,60})$", _uppercase_status_rule),
    # trailing-colon headings such as "First source:"
    (r"^(.+):$", _trailing_colon_rule),
    # "Foo — bar" combinations such as "Device serial — unavailable"
    (r"^(.+?) — (.+)$", _em_dash_rule),
    # size wrapped in parentheses
    (r"\((\d[\d,.]* (?:bytes?|KB|MB|GB|TB))\)", _size_paren_rule),
    # plain byte counts
    (r"^(\d[\d,]*) bytes?$", lambda m: f"{m.group(1)} 字节"),
    # diagnostics report ------------------------------------------------
    (r"^File: (.*)$", lambda m: f"文件：{m.group(1)}"),
    (r"^ERROR: (.*)$", lambda m: f"错误：{m.group(1)}"),
    (r"^File modified time:\s*(.*)$", lambda m: f"文件修改时间：{m.group(1)}"),
    (r"^Filesystem created time:\s*(.*)$", lambda m: f"文件系统创建时间：{m.group(1)}"),
    (r"^Sony XML timestamp:\s*(.*)$", lambda m: f"Sony XML 时间戳：{m.group(1)}"),
    (r"^Embedded metadata time:\s*(.*)$", lambda m: f"内嵌元数据时间：{m.group(1)}"),
    (r"^XMP sidecar time:\s*(.*)$", lambda m: f"XMP 附属文件时间：{m.group(1)}"),
    (r"^Chosen folder date:\s*(.*)$", lambda m: f"选定的文件夹日期：{m.group(1)}"),
    (
        r"^Chosen source:\s*(.*)$",
        lambda m: f"选定来源：{TRANSLATIONS.get(m.group(1), m.group(1))}",
    ),
    (r"^ExifTool metadata:$", lambda m: "ExifTool 元数据："),
    (r"^  unavailable$", lambda m: "  不可用"),
    # copy log ----------------------------------------------------------
    (r"^Copy report: (.*)$", lambda m: f"复制报告：{m.group(1)}"),
    (r"^(.+)\s\+ REMOVED$", lambda m: f"{TRANSLATIONS.get(m.group(1), m.group(1))} + 已删除"),
    (r"^FORMATTED (.+)$", lambda m: f"已格式化 {m.group(1)}"),
    # format service ----------------------------------------------------
    (
        r"^Formatting is not implemented for (.+)\.$",
        lambda m: f"未在 {m.group(1)} 上实现格式化。",
    ),
    (
        r"^UDisks2 service is not available: (.*)$",
        lambda m: f"UDisks2 服务不可用：{m.group(1)}",
    ),
    (r"^Install (.+)\.$", lambda m: f"请安装 {m.group(1)}。"),
    (r"^Could not open (.+)$", lambda m: f"无法打开 {m.group(1)}"),
    # verification / hash log -------------------------------------------
    (
        r"^Starting copy from (.+) to (.+)$",
        lambda m: f"开始从 {m.group(1)} 复制到 {m.group(2)}",
    ),
    (
        r"^Batch verification \((.+)\): (\d+) checked, (\d+) mismatched$",
        lambda m: f"统一校验（{m.group(1)}）：已校验 {m.group(2)} 个，{m.group(3)} 个不一致",
    ),
    (
        r"^Batch verification \((.+)\): (.*)$",
        lambda m: f"统一校验（{m.group(1)}）：{TRANSLATIONS.get(m.group(2), m.group(2))}",
    ),
    (
        r"^Batch verification \((.+)\) skipped because the copy was cancelled\.$",
        lambda m: f"统一校验（{m.group(1)}）已跳过：复制已被中止。",
    ),
    (
        r"^Verifying (\d+) copied file\(s\) with (.+?)\.\.\.$",
        lambda m: f"正在使用 {m.group(2)} 校验 {m.group(1)} 个已复制文件…",
    ),
    (
        r"^Batch verification finished: (\d+) checked, (\d+) mismatch\(es\), (.+) read in (.+)\.$",
        lambda m: (
            f"统一校验完成：已校验 {m.group(1)} 个，{m.group(2)} 个不一致，"
            f"读取 {m.group(3)}，耗时 {m.group(4)}。"
        ),
    ),
    (
        r"^([A-Z][A-Z0-9]{2,12}) MISMATCH: (.+?) does not match (.+?) \((.+)\); "
        r"the source file was kept$",
        lambda m: (
            f"{m.group(1)} 不一致：{m.group(2)} 与 {m.group(3)} 内容不同"
            f"（{m.group(4)}）；源文件已保留"
        ),
    ),
    (
        r"^batch verification failed \((.+)\)$",
        lambda m: f"统一校验失败（{m.group(1)}）",
    ),
    (
        r"^Continue the copy that was interrupted on (.+)\.$",
        lambda m: f"继续 {m.group(1)} 中断的复制。",
    ),
    # Metadata-based file renaming
    (
        r"^Folder tree: (.+)$",
        lambda m: f"文件夹层级：{TRANSLATIONS.get(m.group(1), m.group(1))}",
    ),
    (
        r"^Rename files: (.+) \(date from (.+)\)$",
        lambda m: (
            f"重命名文件：{TRANSLATIONS.get(m.group(1), m.group(1))}"
            f"（日期来自 {TRANSLATIONS.get(m.group(2), m.group(2))}）"
        ),
    ),
    (
        r"^Rename example \(when enabled\): unavailable — (.+)$",
        lambda m: f"重命名示例（启用后）：不可用 — {translate(m.group(1))}",
    ),
    (
        r"^Rename example \(when enabled\): (.+)$",
        lambda m: f"重命名示例（启用后）：{m.group(1)}",
    ),
    (
        r"^Invalid destination file name (.+?): (.+)$",
        lambda m: (
            f"目标文件名无效 {m.group(1)}：{TRANSLATIONS.get(m.group(2), m.group(2))}"
        ),
    ),
    (
        r"^Unknown rename token \{([A-Za-z0-9_]*)\}\. Supported tokens: (.+) and \*\.$",
        lambda m: f"未知的重命名占位符 {{{m.group(1)}}}。可用的占位符：{m.group(2)} 和 *。",
    ),
    (
        r"^Used when “Rename files from metadata” is enabled on the main window\. "
        r"The extension is kept\. Leave the pattern empty to use prefix \+ date \+ "
        r"postfix, or combine tokens for your own scheme: (.+?)\. \* means the "
        r"original name, so “(.+?)” keeps it after the date\.$",
        lambda m: (
            "在主窗口勾选「根据元数据重命名文件」后生效。扩展名始终保留。"
            "通配模式留空时使用「文件前缀 + 日期 + 文件后缀」组合，也可以用这些"
            f"占位符自由组合：{m.group(1)}。* 代表原始文件名，"
            f"例如「{m.group(2)}」会把原文件名放在日期后面。"
        ),
    ),
]

_PATTERNS: list[tuple[re.Pattern[str], RuleFn]] = [
    (re.compile(pattern), rule) for pattern, rule in _PATTERN_SOURCES
]


# ---------------------------------------------------------------------------
# Public translation API
# ---------------------------------------------------------------------------


def get_language() -> str:
    return _current_language


def set_language(language: str) -> None:
    global _current_language
    if language not in SUPPORTED_LANGUAGES:
        return
    _current_language = language
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            _sync_qt_translations(app)
    except Exception:  # pragma: no cover
        pass


def translate(text: Any) -> Any:
    """Translate a single string (no-op for English or unknown strings)."""
    if not isinstance(text, str) or not text:
        return text
    if _current_language == "en":
        return text
    exact = TRANSLATIONS.get(text)
    if exact is not None:
        return exact
    for pattern, rule in _PATTERNS:
        if pattern.match(text):
            try:
                result = rule(pattern.match(text))  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - translation must never crash
                return text
            if result and result != text:
                return result
    return text


def translate_block(text: Any) -> Any:
    """Translate a multi-line block line by line, preserving indentation."""
    if not isinstance(text, str) or not text:
        return text
    if _current_language == "en":
        return text
    translated: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not stripped:
            translated.append(line)
            continue
        indent = line[: len(line) - len(stripped)]
        translated.append(indent + str(translate(stripped)))
    return "\n".join(translated)


def translate_text(text: Any) -> Any:
    """Translate a widget string, falling back to line-by-line for paragraphs."""
    if not isinstance(text, str) or not text:
        return text
    if _current_language == "en":
        return text
    result = translate(text)
    if result != text:
        return result
    if "\n" in text:
        return translate_block(text)
    return text


def translate_log(text: Any) -> Any:
    """Translate copy-log text, including trailing detail in parentheses."""
    if not isinstance(text, str) or not text:
        return text
    if _current_language == "en":
        return text
    result: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not stripped:
            result.append(line)
            continue
        indent = line[: len(line) - len(stripped)]
        result.append(indent + _translate_one_log_line(stripped))
    return "\n".join(result)


_LOG_SIZE_RE = re.compile(r"\((\d[\d,.]* (?:bytes?|KB|MB|GB|TB))\)")


def _translate_one_log_line(line: str) -> str:
    translated = str(translate(line))
    translated = _LOG_SIZE_RE.sub(r"（\1）", translated)
    translated = translated.replace(" + REMOVED", " + 已删除")
    match = re.match(r"^(.*?)(\s\(([^()]*)\))$", translated)
    if not match:
        return translated
    detail = match.group(3)
    parts = [part.strip() for part in detail.split(",")]
    if not any(part in TRANSLATIONS for part in parts):
        return translated
    localised = [TRANSLATIONS.get(part, part) for part in parts]
    return f"{match.group(1)}（{'，'.join(p for p in localised if p)}）"


def _translate_html(html: str) -> str:
    """Translate the text nodes of a simple HTML fragment (log/preview)."""
    if _current_language == "en":
        return html

    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        prefix = re.match(r"^((?:&nbsp;|[ \t])*)", inner)
        lead = prefix.group(1) if prefix else ""
        body = inner[len(lead):]
        if not body.strip():
            return match.group(0)
        return ">" + lead + _translate_one_log_line(body) + "<"

    try:
        return re.sub(r">([^<>]+)<", replace, html)
    except Exception:  # pragma: no cover
        return html



# ---------------------------------------------------------------------------
# Qt integration (runtime patches)
# ---------------------------------------------------------------------------

_SOURCE_ROLE = 0x0100 + 500  # Qt.ItemDataRole.UserRole + 500
_installed = False
_orig: dict[str, Any] = {}


def _store_source(widget: Any, key: str, english: str) -> None:
    try:
        widget.setProperty(f"_i18n_{key}", english)
    except Exception:  # pragma: no cover
        pass


def _source_of(widget: Any, key: str) -> str | None:
    try:
        value = widget.property(f"_i18n_{key}")
    except Exception:  # pragma: no cover
        return None
    return value if isinstance(value, str) and value else None


def _install_patches() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QAbstractButton,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QWidget,
    )

    # --- capture originals ------------------------------------------------
    originals = {
        "label_setText": QLabel.setText,
        "button_setText": QAbstractButton.setText,
        "groupbox_setTitle": QGroupBox.setTitle,
        "lineedit_setPlaceholder": QLineEdit.setPlaceholderText,
        "widget_setWindowTitle": QWidget.setWindowTitle,
        "widget_setToolTip": QWidget.setToolTip,
        "combo_addItem": QComboBox.addItem,
        "combo_insertItem": QComboBox.insertItem,
        "combo_setItemText": QComboBox.setItemText,
        "combo_setItemData": QComboBox.setItemData,
        "tab_addTab": QTabWidget.addTab,
        "tab_setTabText": QTabWidget.setTabText,
        "form_addRow": QFormLayout.addRow,
        "plain_setPlainText": QPlainTextEdit.setPlainText,
        "msg_setText": QMessageBox.setText,
        "msg_setInformative": QMessageBox.setInformativeText,
        "msg_setDetailed": QMessageBox.setDetailedText,
        "msg_addButton": QMessageBox.addButton,
        "textedit_setHtml": QTextEdit.setHtml,
        "textedit_append": QTextEdit.append,
        "textedit_insertHtml": QTextEdit.insertHtml,
    }
    _orig.update(originals)

    # --- plain text setters (remember English, then set the translation) ---
    def make_text_setter(original: Any, key: str) -> Any:
        def wrapper(self: Any, text: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(text, str):
                _store_source(self, key, text)
                text = translate_text(text)
            return original(self, text, *args, **kwargs)

        return wrapper

    QLabel.setText = make_text_setter(originals["label_setText"], "text")
    QAbstractButton.setText = make_text_setter(originals["button_setText"], "text")
    QGroupBox.setTitle = make_text_setter(originals["groupbox_setTitle"], "text")
    QLineEdit.setPlaceholderText = make_text_setter(
        originals["lineedit_setPlaceholder"], "placeholder"
    )
    QWidget.setWindowTitle = make_text_setter(originals["widget_setWindowTitle"], "title")
    QWidget.setToolTip = make_text_setter(originals["widget_setToolTip"], "tooltip")

    # --- combo boxes ------------------------------------------------------
    def combo_addItem(original: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if args and isinstance(args[0], str):
                english = args[0]
                result = original(self, translate(english), *args[1:], **kwargs)
                try:
                    self.setItemData(self.count() - 1, english, _SOURCE_ROLE)
                except Exception:  # pragma: no cover
                    pass
                return result
            return original(self, *args, **kwargs)

        return wrapper

    def combo_addItems(original: Any) -> Any:
        def wrapper(self: Any, texts: Any) -> Any:
            for text in list(texts or []):
                self.addItem(text)
            return None

        return wrapper

    def combo_insertItem(original: Any) -> Any:
        def wrapper(self: Any, index: Any, *args: Any, **kwargs: Any) -> Any:
            if args and isinstance(args[0], str):
                english = args[0]
                result = original(self, index, translate(english), *args[1:], **kwargs)
                try:
                    self.setItemData(index, english, _SOURCE_ROLE)
                except Exception:  # pragma: no cover
                    pass
                return result
            return original(self, index, *args, **kwargs)

        return wrapper

    def combo_setItemText(original: Any) -> Any:
        def wrapper(self: Any, index: Any, text: Any) -> Any:
            if isinstance(text, str):
                try:
                    self.setItemData(index, text, _SOURCE_ROLE)
                except Exception:  # pragma: no cover
                    pass
                text = translate(text)
            return original(self, index, text)

        return wrapper

    def combo_setItemData(original: Any) -> Any:
        def wrapper(self: Any, index: Any, value: Any, role: Any = None) -> Any:
            if (
                isinstance(value, str)
                and role is not None
                and role == Qt.ItemDataRole.ToolTipRole
            ):
                value = translate(value)
            if role is None:
                return original(self, index, value)
            return original(self, index, value, role)

        return wrapper

    QComboBox.addItem = combo_addItem(originals["combo_addItem"])
    QComboBox.addItems = combo_addItems(None)
    QComboBox.insertItem = combo_insertItem(originals["combo_insertItem"])
    QComboBox.setItemText = combo_setItemText(originals["combo_setItemText"])
    QComboBox.setItemData = combo_setItemData(originals["combo_setItemData"])

    # --- tabs -------------------------------------------------------------
    def tab_addTab(original: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            english = None
            if args and isinstance(args[-1], str):
                english = args[-1]
                args = tuple(list(args[:-1]) + [translate(english)])
            result = original(self, *args, **kwargs)
            if english is not None:
                try:
                    self.tabBar().setTabData(self.count() - 1, english)
                except Exception:  # pragma: no cover
                    pass
            return result

        return wrapper

    def tab_setTabText(original: Any) -> Any:
        def wrapper(self: Any, index: Any, text: Any) -> Any:
            if isinstance(text, str):
                try:
                    self.tabBar().setTabData(index, text)
                except Exception:  # pragma: no cover
                    pass
                text = translate(text)
            return original(self, index, text)

        return wrapper

    QTabWidget.addTab = tab_addTab(originals["tab_addTab"])
    QTabWidget.setTabText = tab_setTabText(originals["tab_setTabText"])

    # --- QFormLayout.addRow ----------------------------------------------
    def form_addRow(original: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if args and isinstance(args[0], str):
                english = args[0]
                result = original(self, translate(english), *tuple(args[1:]), **kwargs)
                if len(args) > 1:
                    try:
                        label = self.labelForField(args[1])
                    except Exception:  # pragma: no cover
                        label = None
                    if label is not None:
                        _store_source(label, "text", english)
                return result
            return original(self, *args, **kwargs)

        return wrapper

    QFormLayout.addRow = form_addRow(originals["form_addRow"])

    # --- plain text views (diagnostics / compatibility reports) -----------
    def plain_setPlainText(original: Any) -> Any:
        def wrapper(self: Any, text: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(text, str):
                _store_source(self, "plain", text)
                text = translate_block(text)
            return original(self, text, *args, **kwargs)

        return wrapper

    QPlainTextEdit.setPlainText = plain_setPlainText(originals["plain_setPlainText"])

    # --- constructor text (QLabel("..."), QPushButton("..."), ...) --------
    def ctor_patch(
        cls: Any,
        read: Callable[[Any], str],
        apply: Callable[[Any, str], None],
    ) -> None:
        original = cls.__init__

        def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
            original(self, *args, **kwargs)
            if _source_of(self, "text") is not None:
                return
            try:
                english = read(self)
            except Exception:  # pragma: no cover
                return
            if not english:
                return
            _store_source(self, "text", english)
            translated = translate_text(english)
            if translated != english:
                try:
                    apply(self, translated)
                except Exception:  # pragma: no cover
                    pass

        cls.__init__ = wrapper

    ctor_patch(QLabel, lambda w: w.text(), lambda w, t: originals["label_setText"](w, t))
    ctor_patch(
        QGroupBox, lambda w: w.title(), lambda w, t: originals["groupbox_setTitle"](w, t)
    )
    for button_cls in (QPushButton, QCheckBox, QRadioButton, QToolButton):
        ctor_patch(
            button_cls, lambda w: w.text(), lambda w, t: originals["button_setText"](w, t)
        )
    ctor_patch(
        QPlainTextEdit,
        lambda w: w.toPlainText(),
        lambda w, t: originals["plain_setPlainText"](w, t),
    )

    # --- static dialog helpers -------------------------------------------
    def wrap_message_box(original: Any) -> Any:
        def wrapper(parent: Any, title: Any, text: Any, *args: Any, **kwargs: Any) -> Any:
            return original(parent, translate(title), translate(text), *args, **kwargs)

        return wrapper

    for name in ("critical", "warning", "information", "question", "about"):
        setattr(QMessageBox, name, staticmethod(wrap_message_box(getattr(QMessageBox, name))))

    def wrap_file_dialog(original: Any) -> Any:
        def wrapper(
            parent: Any, caption: Any = "", directory: Any = "", *args: Any, **kwargs: Any
        ) -> Any:
            if isinstance(caption, str):
                caption = translate(caption)
            extra = tuple(translate(a) if isinstance(a, str) else a for a in args)
            return original(parent, caption, directory, *extra, **kwargs)

        return wrapper

    for name in (
        "getExistingDirectory",
        "getOpenFileName",
        "getOpenFileNames",
        "getSaveFileName",
    ):
        setattr(QFileDialog, name, staticmethod(wrap_file_dialog(getattr(QFileDialog, name))))

    def wrap_get_color(original: Any) -> Any:
        def wrapper(
            initial: Any = None, parent: Any = None, title: Any = "", *args: Any, **kwargs: Any
        ) -> Any:
            if isinstance(title, str):
                title = translate(title)
            return original(initial, parent, title, *args, **kwargs)

        return wrapper

    QColorDialog.getColor = staticmethod(wrap_get_color(QColorDialog.getColor))

    # --- QMessageBox instance helpers ------------------------------------
    QMessageBox.setText = make_text_setter(originals["msg_setText"], "msgtext")
    QMessageBox.setInformativeText = make_text_setter(
        originals["msg_setInformative"], "msginfo"
    )
    QMessageBox.setDetailedText = make_text_setter(originals["msg_setDetailed"], "msgdetail")

    def msg_addButton(original: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if args and isinstance(args[0], str):
                args = (translate(args[0]),) + tuple(args[1:])
            return original(self, *args, **kwargs)

        return wrapper

    QMessageBox.addButton = msg_addButton(originals["msg_addButton"])

    # --- rich text views (copy log, colour preview) -----------------------
    def make_html_setter(original: Any) -> Any:
        def wrapper(self: Any, html: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(html, str):
                html = _translate_html(html)
            return original(self, html, *args, **kwargs)

        return wrapper

    QTextEdit.setHtml = make_html_setter(originals["textedit_setHtml"])
    QTextEdit.append = make_html_setter(originals["textedit_append"])
    QTextEdit.insertHtml = make_html_setter(originals["textedit_insertHtml"])


def _sync_qt_translations(app: Any) -> None:
    """Install (or remove) the bundled Qt translations for the active language."""
    try:
        from PySide6.QtCore import QTranslator

        translators = getattr(app, "_i18n_qt_translators", None)
        if not isinstance(translators, list):
            translators = []
            app._i18n_qt_translators = translators

        if _current_language != "zh_CN":
            for translator in translators:
                app.removeTranslator(translator)
            translators.clear()
            return

        if translators:
            return

        from pathlib import Path

        import PySide6
        from PySide6.QtCore import QLibraryInfo

        candidates = [
            Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
            Path(PySide6.__file__).parent / "Qt" / "translations",
        ]
        for base in candidates:
            if not base.exists():
                continue
            translator = QTranslator(app)
            if translator.load("qtbase_zh_CN", str(base)):
                app.installTranslator(translator)
                translators.append(translator)
                break
    except Exception:  # pragma: no cover
        pass


def install(app: Any) -> None:
    """Install the runtime patches.  Safe to call more than once."""
    global _installed
    if not _installed:
        try:
            _install_patches()
            _installed = True
        except Exception:  # pragma: no cover - never block application start
            _installed = False
    _sync_qt_translations(app)


def retranslate_all() -> None:
    """Re-apply translations to every live widget (used on language change)."""
    try:
        from PySide6.QtWidgets import (
            QAbstractButton,
            QApplication,
            QComboBox,
            QGroupBox,
            QLabel,
            QLineEdit,
            QPlainTextEdit,
            QTabWidget,
        )
    except Exception:  # pragma: no cover
        return

    app = QApplication.instance()
    if app is None:
        return

    for widget in app.allWidgets():
        english = _source_of(widget, "text")
        if english is not None:
            translated = translate_text(english)
            setter = None
            if isinstance(widget, QGroupBox):
                setter = _orig.get("groupbox_setTitle")
            elif isinstance(widget, QLabel):
                setter = _orig.get("label_setText")
            elif isinstance(widget, QAbstractButton):
                setter = _orig.get("button_setText")
            if setter is not None:
                try:
                    setter(widget, translated)
                except Exception:
                    pass

        english = _source_of(widget, "title")
        if english is not None and "widget_setWindowTitle" in _orig:
            try:
                _orig["widget_setWindowTitle"](widget, translate_text(english))
            except Exception:
                pass

        english = _source_of(widget, "placeholder")
        if english is not None and isinstance(widget, QLineEdit) and "lineedit_setPlaceholder" in _orig:
            try:
                _orig["lineedit_setPlaceholder"](widget, translate_text(english))
            except Exception:
                pass

        english = _source_of(widget, "tooltip")
        if english is not None and "widget_setToolTip" in _orig:
            try:
                _orig["widget_setToolTip"](widget, translate_text(english))
            except Exception:
                pass

        english = _source_of(widget, "plain")
        if english is not None and isinstance(widget, QPlainTextEdit) and "plain_setPlainText" in _orig:
            try:
                _orig["plain_setPlainText"](widget, translate_block(english))
            except Exception:
                pass

        if isinstance(widget, QComboBox) and "combo_setItemText" in _orig:
            for index in range(widget.count()):
                source = widget.itemData(index, _SOURCE_ROLE)
                if isinstance(source, str):
                    try:
                        _orig["combo_setItemText"](widget, index, translate(source))
                    except Exception:
                        pass

        if isinstance(widget, QTabWidget) and "tab_setTabText" in _orig:
            try:
                tab_bar = widget.tabBar()
            except Exception:
                tab_bar = None
            for index in range(widget.count()):
                source = None
                if tab_bar is not None:
                    try:
                        source = tab_bar.tabData(index)
                    except Exception:
                        source = None
                if isinstance(source, str):
                    try:
                        _orig["tab_setTabText"](widget, index, translate(source))
                    except Exception:
                        pass
