"""Exercise the actual configured request builder and response parser without a network."""
import io
import json
import pytest
from manual2ar.integrations.vlm.client import QwenChatCompletionsClient,extract_json_content,VisionError


def test_explicit_parameters_and_image_schema_reach_the_http_request(monkeypatch):
    settings={'base_url':'https://fixture.invalid/v1','api_key':'fixture-key','model':'fixture-model',
              'timeout_seconds':20,'enable_thinking':False,'temperature':0}
    captured=[]
    def transport(request,timeout):
        payload=json.loads(request.data);captured.append(payload)
        assert request.full_url=='https://fixture.invalid/v1/chat/completions' and timeout==20
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':'```json\n{"found":true}\n```'}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',transport)
    result=QwenChatCompletionsClient(settings).chat_structured('current frame',{'type':'object'},['fixture-image'],256)
    assert result=={'found':True}
    assert captured[0]['model']=='fixture-model' and captured[0]['temperature']==0
    assert captured[0]['enable_thinking'] is False and captured[0]['max_tokens']==256
    assert captured[0]['messages'][1]['content'][0]['image_url']['url'].endswith('fixture-image')
    assert 'fixture-key' not in json.dumps(captured)


@pytest.mark.parametrize('raw',['[]','no structured object','{"found":'])
def test_invalid_vlm_content_is_rejected(raw):
    with pytest.raises(VisionError):extract_json_content(raw)


def test_auto_network_policy_avoids_unavailable_loopback_proxy(monkeypatch):
    from manual2ar.infrastructure.network import trust_environment
    monkeypatch.setattr('urllib.request.proxy_bypass',lambda _:False)
    monkeypatch.setattr('urllib.request.getproxies',lambda:{'https':'http://127.0.0.1:7890'})
    def refused(*args,**kwargs):raise ConnectionRefusedError()
    monkeypatch.setattr('socket.create_connection',refused)
    assert not trust_environment('https://fixture.invalid','auto')
    assert trust_environment('https://fixture.invalid','system')
    assert not trust_environment('https://fixture.invalid','direct')
    # Only loopback proxies are probed/bypassed; remote policies stay in force.
    monkeypatch.setattr('urllib.request.getproxies',lambda:{'https':'http://proxy.example:8080'})
    assert trust_environment('https://fixture.invalid','auto')


def test_vlm_auto_uses_direct_transport_without_mutating_environment(monkeypatch):
    import os
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:7890')
    monkeypatch.setattr('manual2ar.integrations.vlm.client.trust_environment',lambda *a:False)
    captured=[]
    class Direct:
        def open(self,request,timeout):
            captured.append(request.full_url)
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"found":true}'}}]}).encode())
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Direct())
    c=QwenChatCompletionsClient(dict(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',timeout_seconds=1,proxy_mode='auto'))
    assert c.chat_structured('frame',{},[])=={'found':True}
    assert captured and os.environ['HTTPS_PROXY']=='http://127.0.0.1:7890'


def test_transient_tls_eof_is_retryable_but_bad_credentials_are_not(monkeypatch):
    c=QwenChatCompletionsClient(dict(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',timeout_seconds=1))
    assert c._is_retryable_error(VisionError('request failed: [SSL: UNEXPECTED_EOF_WHILE_READING]'))
    assert not c._is_retryable_error(VisionError('API returned HTTP 401: invalid token'))
