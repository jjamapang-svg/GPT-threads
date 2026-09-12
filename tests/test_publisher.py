import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import post_threads as p

class SafetyTests(unittest.TestCase):
    def test_wrong_account_blocks(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"fake-token"}):
            api=p.Meta()
        api.call=Mock(return_value={"id":"1","username":"other-account"})
        with self.assertRaisesRegex(RuntimeError,"Wrong Threads account"):
            api.identity()

    def test_secrets_are_redacted(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"TOPSECRET"}):
            value=p.safe('{"access_token":"OTHERSECRET", "message":"TOPSECRET"}')
        self.assertNotIn("TOPSECRET",value)
        self.assertNotIn("OTHERSECRET",value)

    def test_private_url_rejected(self):
        with patch.object(p.socket,"getaddrinfo",return_value=[(2,1,6,"",("127.0.0.1",443))]):
            with self.assertRaises(ValueError):
                p.validate_url("https://localhost/image.jpg")

    def test_no_redirects_or_html_images(self):
        response=Mock(status_code=302,headers={"Content-Type":"text/html"})
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        with patch.object(p,"validate_url"),patch.object(p.requests,"get",return_value=response):
            with self.assertRaises(ValueError):
                p.validate_image("https://example.com/image.jpg")

    def test_non_json_response_fails(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"fake-token"}):
            api=p.Meta()
        response=Mock(status_code=500,text="upstream failure")
        response.json.side_effect=ValueError()
        api.session.request=Mock(return_value=response)
        with self.assertRaisesRegex(RuntimeError,"non-JSON"):
            api.call("POST","/1/threads")

    def test_verification_requires_image_and_account(self):
        api=Mock()
        api.call.return_value={"id":"2","username":p.ACCOUNT,"permalink":"https://threads.net/test","media_type":"TEXT_POST","text":"approved"}
        with self.assertRaisesRegex(RuntimeError,"text or image"):
            p.verify(api,"2","approved")

    def publish_fixture(self, history, api=None):
        text,url="approved","https://example.com/photo.jpg"
        approval={"status":"approved","account":p.ACCOUNT,"draft_sha256":p.draft_hash(text,url),"image_sha256":"sha"}
        api=api or Mock()
        def read(path, **kwargs):
            return json.dumps(approval if str(path)=="publish_approval.json" else history)
        return text,url,api,read

    def test_reserved_attempt_never_reposts(self):
        key=p.draft_hash("approved","https://example.com/photo.jpg")
        text,url,api,read=self.publish_fixture({"version":1,"posts":{key:{"status":"publishing"}}})
        with patch.object(Path,"read_text",read):
            with self.assertRaisesRegex(RuntimeError,"duplicate blocked"):
                p.publish(api,"1",text,url,"sha")
        api.call.assert_not_called()

    def test_state_push_failure_prevents_creation(self):
        text,url,api,read=self.publish_fixture({"version":1,"posts":{}})
        with patch.object(Path,"read_text",read),patch.object(p,"recent_posts",return_value=[]),patch.object(p,"save",side_effect=RuntimeError("push failed")):
            with self.assertRaisesRegex(RuntimeError,"push failed"):
                p.publish(api,"1",text,url,"sha")
        api.call.assert_not_called()

    def test_existing_remote_text_prevents_creation(self):
        text,url,api,read=self.publish_fixture({"version":1,"posts":{}})
        with patch.object(Path,"read_text",read),patch.object(p,"recent_posts",return_value=[{"text":text}]):
            with self.assertRaisesRegex(RuntimeError,"Matching text"):
                p.publish(api,"1",text,url,"sha")
        api.call.assert_not_called()

    def test_success_persists_before_each_mutation(self):
        text,url,api,read=self.publish_fixture({"version":1,"posts":{}})
        states=[]
        def call(method,endpoint,**params):
            if endpoint.endswith('/threads'):
                self.assertEqual(states[-1],"reserved")
                return {"id":"10"}
            if endpoint.endswith('/threads_publish'):
                self.assertEqual(states[-1],"publishing")
                return {"id":"20"}
            if endpoint=='/10':
                return {"status":"FINISHED"}
            return {"id":"20","username":p.ACCOUNT,"permalink":"https://threads.net/post/20","text":text,"media_type":"IMAGE"}
        api.call.side_effect=call
        def save(history):
            states.append(next(iter(history['posts'].values()))['status'])
        with patch.object(Path,"read_text",read),patch.object(p,"recent_posts",return_value=[]),patch.object(p,"save",side_effect=save):
            p.publish(api,"1",text,url,"sha")
        self.assertEqual(states,["reserved","container_created","publishing","published_unverified","posted"])

if __name__=='__main__':
    unittest.main()
