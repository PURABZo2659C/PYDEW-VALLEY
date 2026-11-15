"""Entry point for the packaged Windows build.
PyInstaller's windowed bootloader gives the process no console, so this
redirects stdout/stderr into a log file and turns a crash into a log
entry plus a message box.
"""

import os
import sys
import traceback


def _user_dir():
	"""The writable folder the game writes to (save, settings, log)."""
	try:
		from settings import ensure_user_data_dir
		return ensure_user_data_dir()
	except Exception:
		# settings itself failed to import - fall back to the same place
		# it would have picked, so the crash log still has a home.
		base = os.environ.get('APPDATA') or os.path.expanduser('~')
		directory = os.path.join(base, 'PydewValley')
		try:
			os.makedirs(directory, exist_ok=True)
		except OSError:
			pass
		return directory


def _open_log(directory):
	try:
		os.makedirs(directory, exist_ok=True)
		return open(os.path.join(directory, 'game.log'), 'a', encoding='utf-8')
	except OSError:
		return None


def _redirect_output(directory):
	"""Send stdout/stderr to the log file when there is no console.
	A frozen windowed build has sys.stdout set to None, so print() is lost.
	"""
	if not getattr(sys, 'frozen', False):
		return None
	handle = _open_log(directory)
	if handle is None:
		return None
	try:
		sys.stdout = handle
		sys.stderr = handle
	except Exception:
		return None
	return handle


def _message_box(title, text):
	"""Show a native message box - there is no console to print to."""
	try:
		import ctypes
		ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
	except Exception:
		pass


def _report_crash(directory):
	detail = traceback.format_exc()
	try:
		handle = _open_log(directory)
		if handle:
			handle.write('\n--- crash ----\n')
			handle.write(detail)
			handle.close()
	except Exception:
		pass
	_message_box(
		'Pydew Valley crashed',
		'The game hit an unexpected error.\n\n'
		'A log was written to:\n%s\n\n'
		'Please report this, including the details below.\n\n%s'
		% (os.path.join(directory, 'game.log'), detail[-800:]))


def main():
	directory = _user_dir()
	handle = _redirect_output(directory)
	try:
		import main as game
		game.Game().run()
	except SystemExit:
		raise
	except Exception:
		_report_crash(directory)
		sys.exit(1)
	finally:
		if handle:
			try:
				handle.flush()
				handle.close()
			except Exception:
				pass


if __name__ == '__main__':
	main()
