import tempfile, unittest
from npu_observer.store import EventStore
from npu_observer.schema import Event
from npu_observer.sessionizer import assign_sessions
from npu_observer.miner import mine, workflow_yaml
from npu_observer.classify import classify_command

class CoreTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify_command('cmake --build build -j'), 'build')
        self.assertEqual(classify_command('nsys profile ./x'), 'profile')

    def test_store_session_mine(self):
        with tempfile.TemporaryDirectory() as td:
            st=EventStore(td+'/db.sqlite')
            for name in ['source.file.saved','build.completed','npu.test.completed','npu.benchmark.completed']:
                e=Event(name=name, cwd='/repo', attributes={'operator':'fa_grad','git':{'repo_root':'/repo','branch':'x'}}).to_dict(); st.insert(e)
            rows=st.rows(); ass=assign_sessions(rows)
            for eid,sid in ass.items(): st.update_session(eid,sid,sid)
            model=mine(st.rows(),0.5)
            self.assertEqual(model['sessions'],1)
            self.assertIn('npu.test.completed', model['core_steps'])
            self.assertIn('name:', workflow_yaml(model))

if __name__=='__main__': unittest.main()
