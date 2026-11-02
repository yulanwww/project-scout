import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from vault_sync import GitSync, SyncError, allowed, check_content

ROOT=Path(__file__).resolve().parents[1]
GIT=shutil.which('git')


@unittest.skipUnless(GIT, "Git is required for synchronization tests")
class SyncTests(unittest.TestCase):
    def git(self, folder, *args):
        return subprocess.run([GIT,'-C',str(folder),*args],check=True,capture_output=True).stdout.decode().strip()

    def setUp(self):
        work=ROOT/'work';work.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=work)
        self.base=Path(self.temp.name)
        self.remote=self.base/'remote.git'
        self.remote.mkdir()
        self.git(self.remote,'init','--bare','--initial-branch=main')
        self.vault=self.base/'vault'
        subprocess.run([GIT,'clone',str(self.remote),str(self.vault)],check=True,capture_output=True)
        self.git(self.vault,'config','user.name','Test')
        self.git(self.vault,'config','user.email','test@example.invalid')
        self.git(self.vault,'config','core.autocrlf','false')
        (self.vault/'Home.md').write_text('original\n',encoding='utf-8')
        self.git(self.vault,'add','Home.md');self.git(self.vault,'commit','-m','initial');self.git(self.vault,'push','origin','main')
        self.other=self.base/'other'
        subprocess.run([GIT,'clone',str(self.remote),str(self.other)],check=True,capture_output=True)
        self.git(self.other,'config','user.name','Other')
        self.git(self.other,'config','user.email','other@example.invalid')
        self.git(self.other,'config','core.autocrlf','false')
        self.sync=GitSync(self.vault,self.base/'state',git=GIT,guard=lambda:None,remote=str(self.remote),branch='main')

    def tearDown(self):
        # Git object files can be read-only on Windows; remove only verified temp tree.
        def repair(func,path,exc):
            os.chmod(path,0o700);func(path)
        target=Path(self.temp.name).resolve()
        self.assertTrue(target.is_relative_to((ROOT/'work').resolve()))
        shutil.rmtree(target,onerror=repair)
        self.temp.cleanup()

    def remote_change(self,name,text):
        (self.other/name).write_text(text,encoding='utf-8')
        self.git(self.other,'add','--',name);self.git(self.other,'commit','-m','remote edit');self.git(self.other,'push','origin','main')

    def test_push_pull_and_no_repeat_commits(self):
        (self.vault/'Local.md').write_text('local note',encoding='utf-8')
        result=self.sync.sync()
        self.assertEqual(result['state'],'synced')
        head=result['commit']
        self.assertEqual(self.sync.sync()['commit'],head)
        self.git(self.other,'pull','--ff-only')
        self.remote_change('Remote.md','remote note')
        self.sync.sync()
        self.assertEqual((self.vault/'Remote.md').read_text(),'remote note')

    def test_nonconflicting_divergence_merges_both(self):
        (self.vault/'Local.md').write_text('local',encoding='utf-8')
        self.remote_change('Remote.md','remote')
        self.sync.sync()
        self.assertEqual((self.vault/'Local.md').read_text(),'local')
        self.assertEqual((self.vault/'Remote.md').read_text(),'remote')
        self.assertEqual(self.git(self.vault,'rev-parse','HEAD'),self.git(self.remote,'rev-parse','main'))

    def test_conflict_keeps_worktree_and_both_backups(self):
        (self.vault/'Home.md').write_text('local edit\n',encoding='utf-8')
        self.remote_change('Home.md','remote edit\n')
        with self.assertRaises(SyncError):self.sync.sync()
        self.assertEqual((self.vault/'Home.md').read_text(),'local edit\n')
        backups=list((self.base/'state/conflicts').rglob('*.md'))
        self.assertEqual({p.read_text() for p in backups},{'local edit\n','remote edit\n'})
        self.assertEqual(self.git(self.vault,'diff','--name-only','--diff-filter=U'),'')
        head=self.git(self.vault,'rev-parse','HEAD')
        with self.assertRaises(SyncError):self.sync.sync()
        self.assertEqual(self.git(self.vault,'rev-parse','HEAD'),head)
        self.assertEqual(len(list((self.base/'state/conflicts').glob('*/index.json'))),1)

    def test_offline_and_push_failure_recover(self):
        (self.vault/'Local.md').write_text('keep me',encoding='utf-8')
        def offline():raise SyncError('offline')
        self.sync.guard=offline
        with self.assertRaises(SyncError):self.sync.sync()
        self.assertEqual((self.vault/'Local.md').read_text(),'keep me')
        self.sync.guard=lambda:None
        real=self.sync.run_git
        def fail_push(*args,**kwargs):
            if args[0]=='push':raise SyncError('network failed')
            return real(*args,**kwargs)
        with patch.object(self.sync,'run_git',side_effect=fail_push):
            with self.assertRaises(SyncError):self.sync.sync()
        committed=self.git(self.vault,'rev-parse','HEAD')
        self.assertEqual(self.sync.sync()['commit'],committed)

    def test_deletions_stop_without_propagating(self):
        (self.vault/'Home.md').unlink()
        with self.assertRaises(SyncError):self.sync.sync()
        self.assertEqual(self.git(self.remote,'show','main:Home.md'),'original')

    def test_remote_deletion_stops_and_preserves_local(self):
        self.git(self.other,'rm','Home.md');self.git(self.other,'commit','-m','delete test');self.git(self.other,'push','origin','main')
        with self.assertRaises(SyncError):self.sync.sync()
        self.assertEqual((self.vault/'Home.md').read_text(),'original\n')

    def test_deny_database_and_credentials(self):
        self.assertFalse(allowed('tools.db'))
        self.assertFalse(allowed('.obsidian/app.json'))
        self.assertFalse(allowed('../outside.md'))
        with self.assertRaises(SyncError):check_content('secret.md',b'ghp_'+b'A'*36)
        (self.vault/'tools.db').write_bytes(b'private')
        with self.assertRaises(SyncError):self.sync.sync()

    def test_lock_prevents_overlap(self):
        with self.sync.lock():
            with self.assertRaises((SyncError,OSError)):
                with self.sync.lock():pass


if __name__=='__main__':unittest.main()
