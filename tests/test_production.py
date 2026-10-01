"""Document structure, provenance gates, explicit review and provider failures."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from mindos.acquisition import UploadProvider, DirectInputProvider, WebSearchProvider, public_url, fetch_public_document
from mindos.production import normalize_candidate_result
from mindos.storage import Storage
from mindos.web_search import SearchUnavailable
from test_knowledge import graph

TEXT='# 基础概念\n\n定义：概念是一类事物的共同属性，实例帮助初学者理解抽象含义。\n\n## 公式与实例\n\n$$x=y+1$$\n\n例子：使用苹果和梨说明水果的共同特征。'
def candidate(source,title='新概念'):
    block=next(b for b in source['metadata']['blocks'] if len(b['text'])>=20)
    return {'understanding':'资料按照标题分层，包含基础定义、公式和说明实例。','candidates':[
        {'id':'c1','title':title,'summary':'资料中概念的共同属性定义','why':'建立后续学习的基础','type':'concept','depth':2,
         'evidence':[{'block_id':block['id'],'quote':block['text']}]}],'relations':[]}
def office_file(name,text):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr(name,text)
    return out.getvalue()

class ProductionTests(unittest.TestCase):
    def test_markdown_hierarchy_formula_example_and_upload_limits(self):
        source=UploadProvider().acquire(filename='笔记.md',data=TEXT.encode()).to_dict()
        blocks=source['metadata']['blocks']
        self.assertIn('formula',[b['kind'] for b in blocks])
        self.assertIn('example',[b['kind'] for b in blocks])
        self.assertEqual(blocks[-1]['section_path'],['基础概念','公式与实例'])
        self.assertTrue(source['metadata']['file_sha256'])
        text_source=UploadProvider().acquire(filename='笔记.txt',data=TEXT.encode('gb18030')).to_dict()
        self.assertEqual(text_source['source_type'],'txt')
        self.assertIn('共同属性',text_source['content'])
        for name,data in [('a.exe',b'a'*100),('../a.txt',b'a'*100),('a.txt',b'a'* (6*1024*1024+1)),('a.docx',b'invalid zip')]:
            with self.subTest(name=name),self.assertRaises(ValueError):UploadProvider().acquire(filename=name,data=data)

    def test_docx_and_pptx_keep_locations_and_headings(self):
        docx='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>基础概念</w:t></w:r></w:p><w:p><w:r><w:t>定义：概念是一类事物的共同属性，可以通过实例建立直觉。</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>概念与例子的对应表</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
        source=UploadProvider().acquire(filename='书.docx',data=office_file('word/document.xml',docx)).to_dict()
        blocks=source['metadata']['blocks'];self.assertEqual(blocks[0]['kind'],'heading')
        self.assertEqual(blocks[1]['paragraph'],2);self.assertEqual(blocks[2]['kind'],'table')
        ppt='''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp><p:nvSpPr><p:ph type="title"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>标题：基础概念</a:t></a:r></a:p></p:txBody></p:sp><p:sp><p:txBody><a:p><a:r><a:t>定义：通过生活中的具体例子说明概念的共同属性。</a:t></a:r></a:p></p:txBody></p:sp></p:sld>'''
        source=UploadProvider().acquire(filename='课件.pptx',data=office_file('ppt/slides/slide1.xml',ppt)).to_dict()
        self.assertTrue(all(b['slide']==1 for b in source['metadata']['blocks']))
        self.assertEqual(source['metadata']['blocks'][1]['kind'],'heading')

    def test_pdf_actual_text_layer_and_page_locator(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 200 Td (A concept describes common properties of real examples.) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        out=io.BytesIO();writer.write(out)
        source=UploadProvider().acquire(filename='book.pdf',data=out.getvalue()).to_dict()
        self.assertIn('common properties',source['content']);self.assertEqual(source['metadata']['blocks'][0]['page'],1)
        self.assertTrue(source['metadata']['warnings'])

    def test_false_quote_and_foreign_block_cannot_enter_graph(self):
        source=DirectInputProvider().acquire(title='定义',text=TEXT).to_dict()
        for evidence in [[{'block_id':'foreign','quote':'不存在的原文引用不能成为来源'}],[{'block_id':'b2','quote':'不存在的原文引用不能成为来源'}],[]]:
            raw=candidate(source);raw['candidates'][0]['evidence']=evidence
            result=normalize_candidate_result(raw,source,1,source['metadata']['blocks'],{'a1','a2'})
            self.assertFalse(result['candidates'][0]['quality']['grounded'])
            with tempfile.TemporaryDirectory() as directory:
                store,cid=self.store(directory);saved=store.save_source('owner',cid,DirectInputProvider().acquire(title='定义',text=TEXT))
                batch=store.save_batch('owner',cid,saved['id'],1,result)
                with self.assertRaises(ValueError):store.review_batch('owner',cid,batch['id'],'verify',['c1'],'')
                self.assertEqual(len(store.graph('owner',cid)['atoms']),2)
                self.assertEqual(store.batch('owner',cid,batch['id'])['status'],'candidate')

    def store(self,directory):
        store=Storage(Path(directory)/'db.sqlite3')
        draft=store.save_draft('owner','课程','','',{'sections':[{'title':'第一节','objective':'基础'},{'title':'第二节','objective':'后续'}]},[])
        cid=store.confirm_draft('owner',draft['id'],1)['id'];store.save_graph('owner',cid,graph());return store,cid

    def test_duplicate_import_keeps_reading_content_and_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            store,cid=self.store(directory)
            section=store.course('owner',cid)['sections'][0]
            store.save_lesson('owner',cid,section['id'],'已有讲解')
            store.learning_event('owner',cid,['a1'],'read')
            store.save_atom_content('owner',cid,'a1','quick','已有原子内容')
            questions=[{'prompt':'共同属性指什么？','choices':{'a':'共同特征','b':'不同特征','c':'颜色','d':'重量'},'atom_ids':['a1']}]
            quiz=store.create_knowledge_quiz('owner',cid,section['id'],questions,[{'answer':'a','explanation':'符合定义'}],scope='atom',target='a1')
            store.submit_quiz('owner',cid,quiz['id'],['a'])
            source=store.save_source('owner',cid,DirectInputProvider().acquire(title='定义',text=TEXT))
            raw=candidate(source,'概念 1');raw['candidates'][0]['summary']='一句话定义'
            result=normalize_candidate_result(raw,source,1,source['metadata']['blocks'],{'a1','a2'})
            batch=store.save_batch('owner',cid,source['id'],1,result)
            store.review_batch('owner',cid,batch['id'],'verify',['c1'],'核对引用')
            atoms=store.graph('owner',cid)['atoms'];self.assertEqual(len(atoms),2)
            self.assertEqual(atoms[0]['summary'],'一句话定义');self.assertTrue(atoms[0]['source_reference'])
            self.assertTrue(store.knowledge_state('owner',cid)['atoms'][0]['read'])
            self.assertEqual(store.atom_detail('owner',cid,'a1')['content']['quick'],'已有原子内容')
            self.assertEqual(store.knowledge_state('owner',cid)['atoms'][0]['rate'],100)
            self.assertEqual(store.atom_detail('owner',cid,'a1')['quizzes'][0]['id'],quiz['id'])
            with self.assertRaises(ValueError):store.review_batch('owner',cid,batch['id'],'verify',['c1'],'')

    def test_cycle_rejected_without_partial_write_and_deprecation_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            store,cid=self.store(directory);source=store.save_source('owner',cid,DirectInputProvider().acquire(title='定义',text=TEXT))
            raw=candidate(source);raw['relations']=[{'from':'a1','to':'c1','type':'requires'},{'from':'c1','to':'a1','type':'requires'}]
            result=normalize_candidate_result(raw,source,1,source['metadata']['blocks'],{'a1','a2'})
            batch=store.save_batch('owner',cid,source['id'],1,result)
            with self.assertRaises(ValueError):store.review_batch('owner',cid,batch['id'],'verify',['c1'],'')
            self.assertEqual(len(store.graph('owner',cid)['atoms']),2)
            self.assertEqual(store.batch('owner',cid,batch['id'])['status'],'candidate')
            store.review_batch('owner',cid,batch['id'],'deprecate',[],'关系不合适')
            self.assertEqual(store.batch('owner',cid,batch['id'])['status'],'deprecated')

    def test_url_private_addresses_and_redirects_rechecked(self):
        for url in ['file:///tmp/key','http://127.0.0.1/','http://[::1]/','http://user:pass@example.org/','https://example.org:8123/']:
            with self.subTest(url=url),self.assertRaises(ValueError):public_url(url)
        public=[(2,1,6,'',('93.184.216.34',80))]
        with patch('mindos.acquisition.socket.getaddrinfo',return_value=public),patch('mindos.acquisition.socket.create_connection') as connect,patch('mindos.acquisition.http.client.HTTPConnection') as connection:
            response=connection.return_value.getresponse.return_value;response.status=302;response.getheader.return_value='http://127.0.0.1/'
            # Second resolution resolves to private address, so redirect cannot issue a request.
            with patch('mindos.acquisition.socket.getaddrinfo',side_effect=[public,[(2,1,6,'',('127.0.0.1',80))]]):
                with self.assertRaises(ValueError):fetch_public_document('http://example.org/')
            self.assertEqual(connect.call_count,1);connect.assert_called_with(('93.184.216.34',80),timeout=12)

    def test_tavily_extract_uses_body_and_fails_closed_on_partial_failure(self):
        provider=WebSearchProvider(SimpleNamespace(api_url='https://api.tavily.com/search',api_key='private-test-key'),'tavily')
        with patch('mindos.acquisition.public_url'),patch('mindos.acquisition.urllib.request.build_opener') as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value=json.dumps({'results':[{'url':'https://example.org/','raw_content':TEXT}]}).encode()
            source=provider.acquire(url='https://example.org/',title='正文')
            self.assertEqual(source.origin,'web_search');self.assertIn('共同属性',source.content)
            request=opener.return_value.open.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/extract'));self.assertNotIn('private-test-key',request.full_url)
            self.assertEqual(request.get_header('Authorization'),'Bearer private-test-key')
            self.assertEqual(json.loads(request.data)['urls'],['https://example.org/'])
            response.read.return_value=b'{"results":[],"failed_results":[{"url":"https://example.org/"}]}'
            with self.assertRaises(SearchUnavailable):provider.acquire(url='https://example.org/')
            response.read.return_value=b'{"results":[{"url":"https://example.org/","content":"only a search snippet"}]}'
            with self.assertRaises(SearchUnavailable):provider.acquire(url='https://example.org/')

    def test_direction_graph_cannot_invent_verified_provenance(self):
        from mindos.model import ModelGateway
        raw=graph();raw['atoms'][0].update(source_reference=[{'url':'https://fake.example/','quote':'invented'}],quality_status='verified')
        course={'title':'课程','goal':'学习','sections':[{'ordinal':i,'title':f'第{i}节','objective':'基础'} for i in (1,2)]}
        with patch.object(ModelGateway,'_json',return_value=raw):
            result=ModelGateway().build_knowledge_graph(course)
        self.assertEqual(result['atoms'][0]['source_reference'],[])
        self.assertEqual(result['atoms'][0]['quality_status'],'candidate')
