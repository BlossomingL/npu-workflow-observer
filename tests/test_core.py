import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from npu_observer.agent import codex_events, codex_session_id, event_from_hook
from npu_observer.classify import classify_command
from npu_observer.cursor_hooks import expected_hook_response, install_cursor_hooks
from npu_observer.linker import link_to_agent_traces
from npu_observer.miner import mine, workflow_yaml
from npu_observer.schema import Event
from npu_observer.sessionizer import assign_sessions
from npu_observer.store import EventStore


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

    def test_cursor_hook_response_and_reasoning_privacy(self):
        self.assertEqual(expected_hook_response('beforeSubmitPrompt'), {'continue': True})
        self.assertEqual(expected_hook_response('afterFileEdit'), {})
        with patch.dict(os.environ, {
            'CURSOR_PROJECT_DIR': '/repo',
            'CURSOR_TRANSCRIPT_PATH': '/tmp/cursor/session-123.jsonl',
            'CURSOR_VERSION': 'test',
        }, clear=False):
            e=event_from_hook('cursor','afterAgentThought',{'text':'private reasoning','duration_ms':42})
        self.assertEqual(e.name,'agent.thought.completed')
        self.assertTrue(e.session_id.startswith('cursor-'))
        self.assertNotIn('text', e.attributes['hook_payload'])
        self.assertFalse(e.attributes['hook_payload']['content_recorded'])

    def test_cursor_install_is_idempotent_and_preserves_existing_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'hooks.json'
            path.write_text(json.dumps({'version':1,'hooks':{'afterFileEdit':[{'command':'echo keep-me'}]}}))
            _,added1=install_cursor_hooks(path)
            _,added2=install_cursor_hooks(path)
            cfg=json.loads(path.read_text())
            commands=[x['command'] for x in cfg['hooks']['afterFileEdit']]
            self.assertIn('echo keep-me',commands)
            self.assertIn('npu-observer agent-hook --provider cursor --hook afterFileEdit',commands)
            self.assertGreater(added1,0)
            self.assertEqual(added2,0)

    def test_codex_nested_session_meta_and_message_mapping(self):
        session='12345678-1234-5678-9abc-123456789abc'
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/f'rollout-2026-09-17T10-00-00-{session}.jsonl'
            rows=[
                {'timestamp':'2026-09-17T10:00:00+00:00','type':'session_meta','payload':{'meta':{'id':session,'session_id':session,'cwd':'/repo','originator':'codex','cli_version':'0.147.0','source':'cli'}}},
                {'timestamp':'2026-09-17T10:00:01+00:00','type':'event_msg','payload':{'type':'user_message','message':'optimize FA grad'}},
                {'timestamp':'2026-09-17T10:00:02+00:00','type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'I changed tiling.'}]}},
                {'timestamp':'2026-09-17T10:00:03+00:00','type':'response_item','payload':{'type':'reasoning','summary':'do not store me'}},
                {'timestamp':'2026-09-17T10:00:04+00:00','type':'event_msg','payload':{'type':'task_complete'}},
            ]
            path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            events=codex_events(path)
        self.assertEqual(codex_session_id(path),session)
        self.assertEqual([e.name for e in events],[
            'agent.session.started','agent.prompt.submitted','agent.response.record',
            'agent.thought.completed','agent.task.completed'
        ])
        self.assertTrue(all(e.session_id == session for e in events))
        self.assertTrue(all(e.cwd == '/repo' for e in events))
        self.assertEqual(events[3].attributes['record'],{'content_recorded':False})

    def test_link_non_agent_event_to_nearby_agent_trace(self):
        events=[
            {
                'event_id':'a','timestamp':'2026-09-17T10:00:00+00:00','source':'agent:codex',
                'trace_id':'trace-1','session_id':'trace-1','cwd':'/repo','attributes':{'git':{'repo_root':'/repo'}},
            },
            {
                'event_id':'b','timestamp':'2026-09-17T10:03:00+00:00','source':'shell',
                'trace_id':None,'session_id':None,'cwd':'/repo','attributes':{'git':{'repo_root':'/repo'}},
            },
            {
                'event_id':'c','timestamp':'2026-09-17T11:00:00+00:00','source':'shell',
                'trace_id':None,'session_id':None,'cwd':'/repo','attributes':{'git':{'repo_root':'/repo'}},
            },
        ]
        linked=link_to_agent_traces(events,window_minutes=30)
        self.assertEqual(linked,{'b':'trace-1'})
        events[1]['trace_id']='trace-1'
        sessions=assign_sessions(events,gap_minutes=45)
        self.assertEqual(sessions['a'],'trace-1')
        self.assertEqual(sessions['b'],'trace-1')
        self.assertNotEqual(sessions['c'],'trace-1')


if __name__=='__main__': unittest.main()
