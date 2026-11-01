import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
import app as module
import voice_chat
from twilio.request_validator import RequestValidator


class Immediate:
    def submit(self, fn, *args):
        fn(*args)


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        module.DB = Path(self.temp.name) / 'tasks.db'
        module.app.config.update(TESTING=True)
        self.env = patch.dict(os.environ, {
            'TWILIO_AUTH_TOKEN': 'test-token', 'RENDER_EXTERNAL_URL': 'https://malak.example',
            'TWILIO_ACCOUNT_SID': 'ACtest', 'TWILIO_FROM_NUMBER': '+15555550100',
            'MALAK_TO_NUMBER': '+15555550101',
            'MALAK_REPLY_MODE': 'openai',
        })
        self.env.start()
        self.client = module.app.test_client()
        con = module.db()
        con.execute("INSERT INTO tasks(title,done) VALUES('مهمة اختبار',1)")
        con.execute("INSERT INTO voice_calls(sid,task_id,title) VALUES('CAtest',1,'مهمة اختبار')")
        con.commit()
        con.close()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def post(self, path, **extra):
        data = {'CallSid': 'CAtest', **extra}
        signature = RequestValidator('test-token').compute_signature('https://malak.example' + path, data)
        return self.client.post(path, data=data, headers={'X-Twilio-Signature': signature})

    def row(self):
        con = module.db()
        row = con.execute("SELECT * FROM voice_calls WHERE sid='CAtest'").fetchone()
        con.close()
        return row

    def test_unsigned_callbacks_rejected_without_mutation(self):
        for path in ['/voice', '/voice/turn', '/voice/wait']:
            self.assertEqual(self.client.post(path, data={'CallSid': 'CAtest', 'Digits': '1'}).status_code, 403)
        self.assertIsNone(self.row()['confirmed_at'])

    def test_arabic_gather_and_no_confirmation_on_silence(self):
        response = self.post('/voice')
        tree = ET.fromstring(response.data)
        self.assertEqual(tree.find('Gather').get('language'), 'ar-SA')
        self.assertIn('speech', tree.find('Gather').get('input'))
        self.assertIsNone(self.row()['confirmed_at'])
        self.post('/voice/turn')
        self.assertIsNone(self.row()['confirmed_at'])

    def test_speech_gets_ai_reply_but_never_auto_confirms(self):
        with patch.object(voice_chat, 'POOL', Immediate()), patch.object(voice_chat, 'ai_reply', return_value='تمام، اضغط واحد للتأكيد.') as ai:
            self.post('/voice/turn', SpeechResult='خلصت المهمة')
        self.assertEqual(ai.call_args.args[0][-1]['content'], 'خلصت المهمة')
        self.assertEqual(ai.call_args.args[1], 'مهمة اختبار')
        self.assertIsNone(self.row()['confirmed_at'])
        self.assertEqual(self.row()['state'], 'ready')
        response = self.post('/voice/wait?n=1')
        self.assertIn('اضغط واحد', response.data.decode())
        self.assertEqual(self.row()['state'], 'listening')

    def test_keypad_confirmation_idempotent_and_visible_on_dashboard(self):
        self.assertEqual(self.post('/voice/turn', Digits='1').status_code, 200)
        saved = self.row()['confirmed_at']
        self.assertTrue(saved)
        self.post('/voice/turn', Digits='1')
        self.post('/voice/turn', Digits='9')
        self.assertEqual(self.row()['confirmed_at'], saved)
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        self.assertIn('تم تأكيدك وحفظه', self.client.get('/').data.decode())

    def test_cancel_cannot_later_confirm(self):
        self.post('/voice/turn', Digits='9')
        self.post('/voice/turn', Digits='1')
        self.assertIsNone(self.row()['confirmed_at'])

    def test_unknown_call_rejected(self):
        self.assertEqual(self.post('/voice', CallSid='CAunknown').status_code, 404)

    def test_task_call_keeps_task_context_and_no_automatic_confirmation(self):
        with patch.object(module, 'Client') as client:
            client.return_value.calls.create.return_value.sid = 'CAcreated'
            module.phone_call(1)
            url = client.return_value.calls.create.call_args.kwargs['url']
            self.assertTrue(url.startswith('https://malak.example/voice?ticket='))
            self.assertGreater(len(url.split('ticket=')[1]), 40)
        con = module.db()
        row = con.execute("SELECT * FROM voice_calls WHERE sid='CAcreated'").fetchone()
        con.close()
        self.assertEqual(row['task_id'], 1)
        self.assertIsNone(row['confirmed_at'])

    def test_openai_failure_preserves_confirmation_fallback(self):
        import urllib.error
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch.object(voice_chat.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError('https://api.openai.com', 429, 'quota', {}, None)):
            result = voice_chat.ai_reply([{'role': 'user', 'content': 'خلصت'}], 'اختبار')
        self.assertIn('واحد', result)
        self.assertIsNone(self.row()['confirmed_at'])

    def test_local_mode_understands_arabic_without_network_or_auto_confirmation(self):
        with patch.dict(os.environ, {'MALAK_REPLY_MODE': 'local'}), patch.object(voice_chat.urllib.request, 'urlopen') as remote:
            for phrase, expected in [('خَلَصْت', 'يعطيك العافية'), ('ما خلصت', 'ما راح أحفظ'), ('ماخلصت', 'ما راح أحفظ'), ('خلصت بس باقي شغلة', 'ما راح أحفظ'), ('وش المهمة؟', 'مهمة اختبار'), ('ما هي المهمة', 'مهمة اختبار'), ('شيء غير مفهوم', 'ما فهمت')]:
                self.assertIn(expected, voice_chat.local_reply(phrase, 'مهمة اختبار'))
            response = self.post('/voice/turn', SpeechResult='خلصت المهمة')
            self.assertIn('يعطيك العافية', response.data.decode())
            self.assertIsNone(ET.fromstring(response.data).find('Redirect'))
            self.assertIsNone(self.row()['confirmed_at'])
            self.assertEqual(self.row()['turns'], 1)
            remote.assert_not_called()
            self.post('/voice/turn', Digits='1')
            self.assertIsNotNone(self.row()['confirmed_at'])

    def test_local_mode_is_default_and_dashboard_describes_it(self):
        with patch.dict(os.environ, {'MALAK_REPLY_MODE': ''}):
            os.environ.pop('MALAK_REPLY_MODE')
            self.assertFalse(voice_chat.uses_openai())
            with self.client.session_transaction() as session:
                session['logged_in'] = True
            text = self.client.get('/').data.decode()
            self.assertIn('الردود العربية الجاهزة مفعلة', text)
            self.assertNotIn('الردود تتطلب رصيد API', text)

    def ticket(self):
        import hashlib
        con = module.db()
        con.execute("UPDATE voice_calls SET ticket_digest=? WHERE sid='CAtest'", (hashlib.sha256(b'test-call-ticket').hexdigest(),))
        con.commit()
        con.close()
        return 'test-call-ticket'

    def test_trial_ticket_starts_voice_and_preserves_ticket_in_gather(self):
        ticket = self.ticket()
        response = self.client.post('/voice?ticket=' + ticket, data={'CallSid': 'CAtest'})
        self.assertEqual(response.status_code, 200)
        gather = ET.fromstring(response.data).find('Gather')
        self.assertEqual(gather.get('action'), 'https://malak.example/voice/turn?ticket=' + ticket)

    def test_ticket_cannot_be_used_for_another_call_or_after_expiry(self):
        ticket = self.ticket()
        self.assertEqual(self.client.post('/voice/turn?ticket=invalid', data={'Digits': '1'}).status_code, 403)
        self.assertEqual(self.client.post('/voice/turn?ticket=' + ticket, data={'CallSid': 'CAother', 'Digits': '1'}).status_code, 403)
        con = module.db()
        con.execute("UPDATE voice_calls SET created_at=datetime('now','-11 minutes')")
        con.commit()
        con.close()
        self.assertEqual(self.client.post('/voice/turn?ticket=' + ticket, data={'CallSid': 'CAtest', 'Digits': '1'}).status_code, 403)
        self.assertIsNone(self.row()['confirmed_at'])

    def test_trial_ticket_handles_speech_then_explicit_confirmation(self):
        ticket = self.ticket()
        with patch.dict(os.environ, {'MALAK_REPLY_MODE': 'local'}), patch.object(voice_chat.urllib.request, 'urlopen') as remote:
            response = self.client.post('/voice/turn?ticket=' + ticket, data={'CallSid': 'CAtest', 'SpeechResult': 'خلصت'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('يعطيك العافية', response.data.decode())
            self.assertIsNone(self.row()['confirmed_at'])
            response = self.client.post('/voice/turn?ticket=' + ticket, data={'CallSid': 'CAtest', 'Digits': '1'})
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(self.row()['confirmed_at'])
            remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
