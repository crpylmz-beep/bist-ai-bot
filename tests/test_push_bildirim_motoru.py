import base64
import json
import tempfile
import threading
import unittest
import urllib.request
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kullanici_kayitlari import UserRecords, RecordError, atomic_json
import push_bildirim_motoru as push
from web_server import create_server


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.records = UserRecords(Path(self.temp.name)/'private', Path(self.temp.name)/'web')
        self.enterContext(patch.object(push, 'validate_endpoint', side_effect=lambda x:x))

    def subscription(self, user='u1', endpoint='https://fcm.googleapis.com/one'):
        encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
        return push.subscription_save(self.records, user, {'endpoint':endpoint, 'keys':{
            'p256dh':encode(b'\x04'+b'x'*64), 'auth':encode(b'x'*16)}, 'browser_id':'browser'})

    def event(self, user='u1', identifier='e1'):
        with self.records.locked(push.OUTBOX) as (path,data):
            data.setdefault('pending_notifications',{}).setdefault(user,[]).append({
                'id':identifier,'status':'PENDING','sembol':'THYAO','kaynak':'MANUEL', 'triggered_price':300})
            atomic_json(path,data)

    def stored(self):
        return json.loads((self.records.data_dir/push.OUTBOX).read_text())['pending_notifications']

    def test_subscription_is_private_idempotent_and_disabled(self):
        saved=self.subscription(); self.assertEqual(saved,self.subscription())
        path=self.records.data_dir/push.SUBSCRIPTIONS
        data=json.loads(path.read_text())
        self.assertEqual(len(data['kullanicilar']['u1']),1)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertTrue(data['kullanicilar']['u1'][saved['id']]['created_at'].endswith('+03:00'))
        with self.assertRaises(RecordError):self.subscription('u2')
        with self.assertRaises(RecordError):push.subscription_disable(self.records,'u2',saved['id'])
        push.subscription_disable(self.records,'u1',saved['id'])
        self.event(); sender=Mock(); push.bildirimleri_gonder(self.records,sender); sender.assert_not_called()

    def test_sent_duplicate_and_user_isolation(self):
        self.subscription(); self.subscription('u2','https://fcm.googleapis.com/two')
        self.event(); self.event('u2','e2'); sender=Mock()
        push.bildirimleri_gonder(self.records,sender); push.bildirimleri_gonder(self.records,sender)
        self.assertEqual(sender.call_count,2)
        for owner,rows in self.stored().items():
            self.assertEqual(rows[0]['status'],'SENT');self.assertTrue(rows[0]['sent_at'].endswith('+03:00'))
        self.assertEqual(sender.call_args_list[0].args[0]['user_id'],'u1')
        self.assertEqual(sender.call_args_list[1].args[0]['user_id'],'u2')
        self.assertEqual(sender.call_args_list[0].args[1]['url'],'/?stock=THYAO')

    def test_failed_retry_does_not_resend_successful_browser(self):
        self.subscription(); self.subscription(endpoint='https://fcm.googleapis.com/two'); self.event()
        calls=[]
        def sender(sub,payload):
            calls.append(sub['endpoint'])
            if sub['endpoint'].endswith('two') and calls.count(sub['endpoint'])==1:raise RuntimeError('secret endpoint')
        push.bildirimleri_gonder(self.records,sender)
        self.assertEqual(self.stored()['u1'][0]['retry_count'],1)
        self.assertNotIn('secret',json.dumps(self.stored()))
        push.bildirimleri_gonder(self.records,sender)
        self.assertEqual(calls.count('https://fcm.googleapis.com/one'),1)
        self.assertEqual(self.stored()['u1'][0]['status'],'SENT')

    def test_expired_endpoint_disabled(self):
        sub=self.subscription(); self.event()
        error=RuntimeError();error.response=SimpleNamespace(status_code=410)
        sender=Mock(side_effect=error)
        push.bildirimleri_gonder(self.records,sender);push.bildirimleri_gonder(self.records,sender)
        sender.assert_called_once()
        data=json.loads((self.records.data_dir/push.SUBSCRIPTIONS).read_text())
        self.assertFalse(data['kullanicilar']['u1'][sub['id']]['active'])

    def test_timeout_keeps_uncertain_claim_without_resend(self):
        self.subscription();self.event();sender=Mock(side_effect=TimeoutError())
        push.bildirimleri_gonder(self.records,sender);push.bildirimleri_gonder(self.records,sender)
        sender.assert_called_once()
        delivery=next(iter(self.stored()['u1'][0]['deliveries'].values()))
        self.assertEqual(delivery['status'],'SENDING')

    def test_atomic_claim_failure_sends_nothing_and_preserves_outbox(self):
        self.subscription();self.event();sender=Mock()
        path=self.records.data_dir/push.OUTBOX; before=path.read_bytes()
        with patch.object(push,'atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):push.bildirimleri_gonder(self.records,sender)
        sender.assert_not_called();self.assertEqual(path.read_bytes(),before)

    def test_endpoint_and_key_validation(self):
        # Call the actual implementation independently of the fixture DNS bypass.
        from importlib.util import spec_from_file_location, module_from_spec
        spec=spec_from_file_location('push_validation',push.__file__);module=module_from_spec(spec);spec.loader.exec_module(module)
        for endpoint in ('http://fcm.googleapis.com/x','https://localhost/x','https://example.com/x'):
            with self.assertRaises(RecordError):module.validate_endpoint(endpoint)
        with patch.object(module.socket,'getaddrinfo',return_value=[(0,0,0,'',('127.0.0.1',443))]):
            with self.assertRaises(RecordError):module.validate_endpoint('https://fcm.googleapis.com/x')
        with patch.object(module.socket,'getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443))]):
            self.assertEqual(module.validate_endpoint('https://fcm.googleapis.com/x'),'https://fcm.googleapis.com/x')
        with self.assertRaises(RecordError):push.subscription_save(self.records,'u1',{'endpoint':'https://fcm.googleapis.com/x','keys':{'p256dh':'bad','auth':'bad'},'browser_id':'test'})

    def test_concurrent_rounds_and_crash_claim_do_not_duplicate(self):
        self.subscription();self.event();sender=Mock()
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:push.bildirimleri_gonder(self.records,sender),range(2)))
        sender.assert_called_once()
        self.event(identifier='crash')
        with self.assertRaises(KeyboardInterrupt):push.bildirimleri_gonder(self.records,Mock(side_effect=KeyboardInterrupt))
        sender.reset_mock();push.bildirimleri_gonder(self.records,sender);sender.assert_not_called()

    def test_http_api_static_pwa_and_cross_site_write(self):
        server=create_server('127.0.0.1',0,self.records)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        for path in ('/','/service-worker.js','/manifest.webmanifest','/icon-192.png','/api/push/config'):
            with client.open(base+path) as response:
                self.assertEqual(response.status,200);response.read()
        encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
        body=json.dumps({'endpoint':'https://fcm.googleapis.com/http','browser_id':'http',
             'keys':{'p256dh':encode(b'\x04'+b'x'*64),'auth':encode(b'x'*16)}}).encode()
        headers={'Content-Type':'application/json','X-Bist-Request':'1'}
        req=urllib.request.Request(base+'/api/push/subscriptions',data=body,headers=headers)
        with client.open(req) as response: saved=json.load(response)
        req=urllib.request.Request(base+'/api/push/subscriptions/'+saved['id'],method='DELETE',headers=headers)
        with client.open(req) as response:self.assertFalse(json.load(response)['active'])
        headers['Origin']='https://evil.example'
        with self.assertRaises(urllib.error.HTTPError) as error:client.open(urllib.request.Request(base+'/api/push/subscriptions',data=body,headers=headers))
        self.assertEqual(error.exception.code,403)


if __name__=='__main__':unittest.main()
