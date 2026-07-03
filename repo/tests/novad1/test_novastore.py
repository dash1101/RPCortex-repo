# novastore: the code persistence layer. Exercised against a REAL temp dir by pointing
# _FLASH at it and routing the stubbed uos to the real os (save/list/read/rename/delete).
import sys
import os
import tempfile
import _shims
_shims.install()
from _shims import T
import novastore as S

t = T('test_novastore')

# Point the store at a throwaway dir + give it real filesystem ops.
_tmp = tempfile.mkdtemp()
S._FLASH = os.path.join(_tmp, 'codes')
_u = sys.modules['uos']
_u.mkdir = os.mkdir
_u.listdir = os.listdir
_u.remove = os.remove

# save + read round-trip
p = S.save_code('ir', 'tv.ir', 'DATA 1 2 3')
t.ok(os.path.exists(p), 'save_code writes the file to flash')
t.eq(S.read_code('ir', 'tv.ir'), 'DATA 1 2 3', 'read_code returns the saved text')
t.ok(S.saving(), 'saving() true after a save queues a backup')

# listing + category isolation
S.save_code('ir', 'ac.ir', 'x')
S.save_code('subghz', 'gate.sub', 'y')
t.eq(S.list_codes('ir'), ['ac.ir', 'tv.ir'], 'list_codes is sorted + per-category')
t.eq(S.list_codes('subghz'), ['gate.sub'], 'categories are isolated')
t.eq(S.list_codes('lora'), [], 'empty category -> []')

# missing reads
t.eq(S.read_code('ir', 'nope.ir'), None, 'missing code -> None')

# rename moves content, drops the old name
t.ok(S.rename_code('ir', 'tv.ir', 'telly.ir'), 'rename returns True')
t.eq(S.read_code('ir', 'telly.ir'), 'DATA 1 2 3', 'renamed keeps content')
t.eq(S.read_code('ir', 'tv.ir'), None, 'old name gone after rename')
t.ok(not S.rename_code('ir', 'ghost.ir', 'x.ir'), 'rename of a missing code -> False')

# delete
t.ok(S.delete_code('ir', 'ac.ir'), 'delete returns True')
t.ok('ac.ir' not in S.list_codes('ir'), 'deleted code is gone')
t.ok(not S.delete_code('ir', 'ac.ir'), 'delete of a missing code -> False')

sys.exit(t.done())
