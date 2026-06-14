# Desc: Backup — snapshot and restore RPCortex configuration
# File: /Packages/Backup/backup.py
# Version: 1.0.0
# Author: dash1101
#
# Copies the device's registry and account/config files into a named snapshot
# under /Pulsar/Backups/, so you can roll back after experimenting with
# settings, users, WiFi, aliases, or startup/scheduled tasks. Fully offline.
#
# Usage:
#   backup create [name]    snapshot the config (default name = a timestamp)
#   backup list             list saved snapshots with size and file count
#   backup restore <name>   copy a snapshot's files back into the registry
#   backup remove <name>    delete a snapshot
#   backup info             what gets backed up and where
#
# Notes:
#   - Restore overwrites the live config files, then a reboot is recommended.
#   - Each file is copied in 512-byte chunks — no whole-file RAM read.

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi

_SRC_DIR = '/Pulsar/Registry'
_BAK_DIR = '/Pulsar/Backups'
_FILES = ('registry.cfg', 'user.cfg', 'networks.cfg',
          'aliases.cfg', 'startup.cfg', 'tasks.cfg')


def _exists(path):
    import uos
    try:
        uos.stat(path)
        return True
    except OSError:
        return False


def _isdir(path):
    import uos
    try:
        return bool(uos.stat(path)[0] & 0x4000)
    except OSError:
        return False


def _ensure_dir(path):
    import uos
    if not _exists(path):
        try:
            uos.mkdir(path)
        except OSError as e:
            error("Could not create {}: {}".format(path, e))
            return False
    return True


def _copy(src, dst):
    """Stream-copy src -> dst in 512-byte chunks. Returns bytes copied or -1."""
    try:
        total = 0
        with open(src, 'rb') as fi:
            with open(dst, 'wb') as fo:
                while True:
                    chunk = fi.read(512)
                    if not chunk:
                        break
                    fo.write(chunk)
                    total += len(chunk)
        return total
    except OSError as e:
        error("Copy failed ({} -> {}): {}".format(src, dst, e))
        return -1


def _timestamp():
    import utime
    try:
        t = utime.localtime()
        return '{:04d}{:02d}{:02d}-{:02d}{:02d}{:02d}'.format(
            t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return 'backup-{}'.format(utime.ticks_ms())


def _create(name):
    import uos
    if not _ensure_dir(_BAK_DIR):
        return
    if not name:
        name = _timestamp()
    dest = _BAK_DIR + '/' + name
    if _exists(dest):
        error("A backup named '{}' already exists.".format(name))
        info("Use a different name or 'backup remove {}' first.".format(name))
        return
    if not _ensure_dir(dest):
        return

    saved = 0
    total_bytes = 0
    for f in _FILES:
        src = _SRC_DIR + '/' + f
        if not _exists(src):
            continue
        n = _copy(src, dest + '/' + f)
        if n >= 0:
            saved += 1
            total_bytes += n
    if saved == 0:
        warn("No config files found to back up.")
        try:
            uos.rmdir(dest)
        except OSError:
            pass
        return
    ok("Backup '{}' created — {} files, {} bytes.".format(name, saved, total_bytes))
    info("Restore later with: backup restore {}".format(name))


def _list():
    import uos
    if not _isdir(_BAK_DIR):
        info("No backups yet. Create one with: backup create")
        return
    try:
        names = sorted(uos.listdir(_BAK_DIR))
    except OSError:
        info("No backups yet. Create one with: backup create")
        return
    if not names:
        info("No backups yet. Create one with: backup create")
        return
    info("Backups in {}:".format(_BAK_DIR))
    for name in names:
        d = _BAK_DIR + '/' + name
        if not _isdir(d):
            continue
        count = 0
        size = 0
        try:
            for f in uos.listdir(d):
                count += 1
                try:
                    size += uos.stat(d + '/' + f)[6]
                except OSError:
                    pass
        except OSError:
            pass
        multi("  {:<22} {} files  {} bytes".format(name, count, size))


def _restore(name):
    if not name:
        warn("Usage: backup restore <name>")
        return
    src = _BAK_DIR + '/' + name
    if not _isdir(src):
        error("No backup named '{}'. See 'backup list'.".format(name))
        return
    confirm = None
    try:
        from RPCortex import inpt
        confirm = inpt("Overwrite live config from '{}'? (yes/no)".format(name))
    except Exception:
        confirm = 'yes'
    if not confirm or confirm.strip().lower() != 'yes':
        info("Cancelled.")
        return

    if not _ensure_dir(_SRC_DIR):
        return
    restored = 0
    import uos
    try:
        files = uos.listdir(src)
    except OSError as e:
        error("Cannot read backup: {}".format(e))
        return
    for f in files:
        n = _copy(src + '/' + f, _SRC_DIR + '/' + f)
        if n >= 0:
            restored += 1
    ok("Restored {} files from '{}'.".format(restored, name))
    warn("Reboot to apply the restored configuration.")


def _remove(name):
    if not name:
        warn("Usage: backup remove <name>")
        return
    import uos
    d = _BAK_DIR + '/' + name
    if not _isdir(d):
        error("No backup named '{}'.".format(name))
        return
    try:
        for f in uos.listdir(d):
            try:
                uos.remove(d + '/' + f)
            except OSError:
                pass
        uos.rmdir(d)
        ok("Removed backup '{}'.".format(name))
    except OSError as e:
        error("Could not remove '{}': {}".format(name, e))


def _info():
    info("=== Backup ===")
    multi("  Snapshots: {}".format(_BAK_DIR))
    multi("  Includes : " + ', '.join(_FILES))
    multi("")
    multi("  create [name]   snapshot now (default name = timestamp)")
    multi("  list            show saved snapshots")
    multi("  restore <name>  copy a snapshot back (overwrites live config)")
    multi("  remove <name>   delete a snapshot")
    multi("")
    multi("  User home directories are NOT included — only the config files.")


def backup(args=None):
    if args and args.strip() and args.split()[0].lower() in ('help', '-h', '--help', '?'):
        _info()
        return
    if not args or not args.strip():
        _info()
        return
    parts = args.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ''

    if sub == 'create':
        _create(rest)
    elif sub == 'list':
        _list()
    elif sub == 'restore':
        _restore(rest)
    elif sub in ('remove', 'rm', 'delete'):
        _remove(rest)
    elif sub == 'info':
        _info()
    else:
        error("Unknown subcommand '{}'. Try 'backup info'.".format(sub))
