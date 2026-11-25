"""Offline fixtures only; not live API evidence."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from other_code import quiz1 as q
from other_code.local_qwen import _parse_response

class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.t=q.TravelTools()
        self.t.places=[dict(id='p1',name='京都駅 sweets',summary='甜點',url='https://example.org/1'),dict(id='p2',name='Kyoto Station shopping',summary='百貨',url='https://example.org/2'),dict(id='p3',name='大阪 cafe',summary='咖啡',url='https://example.org/3')]
        self.stops=[dict(place_id='p1',activity='甜點',stay_minutes=45),dict(place_id='p2',activity='購物',stay_minutes=55)]

    def test_filters(self):
        self.assertEqual([p['id'] for p in self.t.filter_by_area('京都站')['places']],['p1','p2'])
        self.assertEqual([p['id'] for p in self.t.filter_by_category('甜點')['places']],['p1'])
        self.assertEqual(self.t.filter_by_category('滑雪')['places'],[])
        with self.assertRaises(ValueError): self.t.filter_by_area('京都站',['bad'])

    def test_schedule(self):
        p=self.t.build_itinerary(120,self.stops)
        self.assertEqual(p['used_minutes_estimate'],110)
        self.assertEqual(p['stops'][1]['start'],'14:55')
        self.assertEqual(p['stops'][0]['opening_hours'],'待確認')
        p=self.t.build_itinerary(50,self.stops)
        self.assertEqual(len(p['omitted']),1)
        with self.assertRaises(ValueError): self.t.build_itinerary(-1,self.stops)

    def test_export(self):
        with self.assertRaises(ValueError): self.t.export_itinerary()
        self.t.build_itinerary(120,self.stops)
        (q.ROOT/'.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=q.ROOT/'.cache') as tmp,patch.object(q,'ROOT',Path(tmp)):
            a=Path(self.t.export_itinerary()['path'])
            b=Path(self.t.export_itinerary()['path'])
            self.assertNotEqual(a,b)
            self.assertIn('https://example.org/1',a.read_text(encoding='utf-8'))
            self.assertIn('估計',a.read_text(encoding='utf-8'))

    def test_agent_guard(self):
        m=dict(role='assistant',tool_calls=[dict(id='call_export',type='function',function=dict(name='export_itinerary',arguments={}))])
        with patch.object(q,'qwen_chat',return_value=m):
            result=q.TravelChat(max_rounds=1).send('只找地點')
        self.assertIn('輪數上限',result['error'])
        self.assertIn('未要求存檔',result['trace'][0]['result']['error'])

    def test_local_qwen_failure_is_reported_by_agent(self):
        with patch.object(q, 'qwen_chat', side_effect=q.LocalModelError('missing weights')):
            result = q.TravelChat().send('找地點')
        self.assertEqual(result['error'], 'missing weights')
        self.assertEqual(result['trace'][0]['tool'], 'Qwen')

    def test_qwen_tool_roundtrip(self):
        first = '<tool_call>{"name":"search_places","arguments":{"area":"京都站","activities":"甜點"}}</tool_call>'
        count = 0

        def respond(messages, model, tools):
            nonlocal count
            count += 1
            self.assertEqual(len(tools), 5)
            if count == 1:
                return _parse_response(first)
            self.assertEqual(messages[-1]['role'], 'tool')
            self.assertEqual(messages[-1]['tool_call_id'], messages[-2]['tool_calls'][0]['id'])
            self.assertIn('https://example.org/1', messages[-1]['content'])
            return _parse_response('找到了候選地點<|im_end|>')

        with patch.object(q, 'qwen_chat', side_effect=respond):
            result = q.TravelChat(snapshot=self.t.places).send('找京都站甜點')
        self.assertIsNone(result['error'])
        self.assertEqual(result['final'], '找到了候選地點')
        self.assertEqual(count, 2)
        with self.assertRaises(q.LocalModelError):
            _parse_response('<tool_call>{bad}</tool_call>')

    def test_multiturn_protocol(self):
        def call(name,args):
            return dict(role='assistant',tool_calls=[dict(id='call_' + name,type='function',function=dict(name=name,arguments=args))])
        end=dict(role='assistant',content='fixture final')
        chat=q.TravelChat(snapshot=self.t.places)
        (q.ROOT/'.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=q.ROOT/'.cache') as tmp,patch.object(q,'ROOT',Path(tmp)):
            with patch.object(q,'qwen_chat',side_effect=[call('search_places',dict(area='京都站',activities='甜點 購物')),end]):
                first=chat.send('找地點')
            with patch.object(q,'qwen_chat',side_effect=[call('build_itinerary',dict(available_minutes=120,stops=self.stops)),end]):
                second=chat.send('沿用排兩小時')
            with patch.object(q,'qwen_chat',side_effect=[call('export_itinerary',{}),end]):
                third=chat.send('把剛才行程存成Markdown')
            self.assertFalse(first['exports'])
            self.assertFalse(second['exports'])
            self.assertTrue(Path(third['exports'][0]).exists())
            self.assertEqual(len([m for m in chat.messages if m['role']=='user']),3)

if __name__=='__main__': unittest.main()
