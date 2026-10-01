"""Replaceable source providers and structure-preserving document normalization."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import http.client
import io
import ipaddress
import json
import re
import secrets
import socket
import ssl
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from .web_search import NoRedirect, SearchUnavailable

MAX_FILE = 6 * 1024 * 1024
MAX_TEXT = 100_000


@dataclass
class SourceDocument:
    id: str
    title: str
    source_type: str
    origin: str
    content: str
    metadata: dict
    created_time: str
    processing_status: str = 'ready'

    def to_dict(self) -> dict:
        return asdict(self)


def document(title: str, kind: str, origin: str, blocks: list[dict], **metadata) -> SourceDocument:
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 150:
        raise ValueError('请填写 1—150 字的资料名称')
    blocks = [b for b in blocks if isinstance(b.get('text'), str) and b['text'].strip()]
    content = '\n\n'.join(b['text'] for b in blocks)
    if not 20 <= len(content) <= MAX_TEXT or len(blocks) > 2000:
        raise ValueError('资料需有至少 20 字可读文本，最多 10 万字、2000 个结构块；请缩小资料范围')
    heading_path = []
    for index, block in enumerate(blocks, 1):
        block['id'] = f'b{index}'
        if block['kind'] == 'heading':
            level = block.get('level', 1)
            heading_path = heading_path[:max(0, level - 1)] + [block['text']]
        block['section_path'] = list(heading_path)
    metadata.update({'blocks': blocks, 'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
                     'extraction_scope': 'available_text', 'warnings': metadata.get('warnings', [])})
    return SourceDocument(secrets.token_urlsafe(16), title.strip(), kind, origin, content, metadata,
                          datetime.now(timezone.utc).isoformat(timespec='seconds'))


def text_blocks(text: str, **locator) -> list[dict]:
    if not isinstance(text, str):
        raise ValueError('资料文本格式无效')
    blocks, paragraph, start = [], [], 1
    def flush():
        if paragraph:
            value = '\n'.join(paragraph).strip()
            kind = ('formula' if value.startswith(('$$', '\\[', '公式')) else
                    'example' if re.match(r'(例[子题]?|示例|Example)[:：\s\d]', value, re.I) else
                    'caption' if re.match(r'(图|表|Figure|Table)\s*\d', value, re.I) else
                    'definition' if re.match(r'(定义|Definition)[:：\s]', value, re.I) else 'paragraph')
            blocks.append({'kind': kind, 'text': value, 'line': start, **locator})
            paragraph.clear()
    code = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith('```'):
            code = not code
        heading = None if code else re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        numbered = None if code else re.match(r'^(第[一二三四五六七八九十百\d]+[章节]\s*.+|\d+(?:\.\d+)+\s+[^。！？]{2,80})$', line.strip())
        if heading or numbered:
            flush()
            level = len(heading[1]) if heading else 1 if line.strip().startswith('第') else line.strip().split()[0].count('.') + 1
            blocks.append({'kind': 'heading', 'level': min(level,6), 'text': heading[2] if heading else line.strip(),
                           'line': number, **locator})
        elif not line.strip() and not code:
            flush()
        else:
            if not paragraph: start = number
            paragraph.append(line)
    flush()
    return blocks


class AcquisitionProvider(ABC):
    @abstractmethod
    def acquire(self, **kwargs) -> SourceDocument:
        """Produce a normalized source with real locator metadata."""


class DirectInputProvider(AcquisitionProvider):
    def acquire(self, *, title: str, text: str, **kwargs) -> SourceDocument:
        return document(title, 'text', 'direct_input', text_blocks(text), parser='structured-text-v1')


class UploadProvider(AcquisitionProvider):
    def acquire(self, *, filename: str, data: bytes, **kwargs) -> SourceDocument:
        if not isinstance(filename, str) or len(filename) > 150 or '/' in filename or '\\' in filename:
            raise ValueError('上传文件名无效')
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_FILE:
            raise ValueError('单个文件最多 6 MB')
        kind = filename.rsplit('.',1)[-1].lower()
        warnings = []
        try:
            if kind in ('md', 'markdown', 'txt'):
                try: text = data.decode('utf-8-sig')
                except UnicodeDecodeError: text = data.decode('gb18030')
                blocks = text_blocks(text)
            elif kind == 'pdf':
                try: from pypdf import PdfReader
                except ImportError as exc: raise ValueError('请安装 requirements.txt 中的 pypdf 后解析 PDF') from exc
                reader = PdfReader(io.BytesIO(data), strict=True)
                if reader.is_encrypted or len(reader.pages) > 200:
                    raise ValueError('暂不支持加密 PDF 或超过 200 页的 PDF')
                blocks = []
                for number, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ''
                    if not text.strip(): warnings.append(f'第 {number} 页没有可提取文本；未进行 OCR')
                    blocks.extend(text_blocks(text, page=number))
                warnings.append('PDF 仅提取文本层，图像、公式布局和复杂表格可能不完整，请核对原文件')
            elif kind in ('docx', 'pptx'):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 40*1024*1024:
                        raise ValueError('压缩文档展开过大，请缩小文件')
                    blocks = []
                    if kind == 'docx':
                        root = ET.fromstring(archive.read('word/document.xml'))
                        ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                        paragraph_number=0;table_number=0
                        for child in root.find('w:body',ns):
                            if child.tag.endswith('}p'):
                                paragraph_number+=1
                                text=''.join(n.text or '' for n in child.iter() if n.tag.endswith('}t'))
                                style=child.find('w:pPr/w:pStyle',ns)
                                name=style.get('{'+ns['w']+'}val','') if style is not None else ''
                                match=re.search(r'(?:heading|标题)\s*([1-6])',name,re.I)
                                if match and text.strip():
                                    blocks.append({'kind':'heading','text':text,'level':int(match[1]),'paragraph':paragraph_number})
                                elif text.strip():blocks.extend(text_blocks(text,paragraph=paragraph_number))
                            elif child.tag.endswith('}tbl'):
                                table_number+=1
                                rows=[' | '.join(''.join(n.text or '' for n in cell.iter() if n.tag.endswith('}t'))
                                                 for cell in row.findall('w:tc',ns)) for row in child.findall('w:tr',ns)]
                                blocks.append({'kind':'table','text':'\n'.join(rows),'table':table_number})
                    else:
                        names = sorted((n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),
                                       key=lambda n:int(re.search(r'slide(\d+)',n)[1]))
                        if len(names) > 200: raise ValueError('演示文稿最多 200 页')
                        for slide, name in enumerate(names,1):
                            root = ET.fromstring(archive.read(name))
                            blocks.append({'kind':'heading','level':1,'text':f'幻灯片 {slide}','slide':slide})
                            for shape in root.iter():
                                if not shape.tag.endswith('}sp'): continue
                                texts = [n.text for n in shape.iter() if n.tag.endswith('}t') and n.text]
                                if texts:
                                    title = any(n.tag.endswith('}ph') and n.get('type') in ('title','ctrTitle') for n in shape.iter())
                                    blocks.append({'kind':'heading' if title else 'paragraph', 'level':2,
                                                   'text':'\n'.join(texts),'slide':slide})
                    warnings.append('Office 文档仅解析文字和表格文字，不执行宏，不识别图片；复杂公式请核对原文件')
            else:
                raise ValueError('支持 PDF、DOCX、PPTX、Markdown 和 TXT')
        except (zipfile.BadZipFile, ET.ParseError, KeyError, UnicodeDecodeError) as exc:
            raise ValueError('文件格式损坏或文字编码无法识别') from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('文件无法解析，请检查是否损坏、加密或使用了不支持的格式') from exc
        return document(filename, 'markdown' if kind == 'md' else kind, 'user_upload', blocks,
                        filename=filename, parser='document-structure-v1', warnings=warnings,
                        file_sha256=hashlib.sha256(data).hexdigest())


def public_url(url: str) -> tuple[urllib.parse.SplitResult, str]:
    if not isinstance(url,str) or len(url)>2000:
        raise ValueError('网页地址格式无效')
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or any(c.isspace() for c in url)
                or parsed.port not in (None, 80 if parsed.scheme=='http' else 443)):
            raise ValueError('请提供不含账号和片段的公开 HTTP(S) 网页地址')
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80), type=socket.SOCK_STREAM)
        ips = [item[4][0] for item in addresses]
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError('只能获取公开网页，不读取本机或内网地址')
        return parsed, ips[0]
    except (socket.gaierror,OSError) as exc:
        raise SearchUnavailable('网页域名解析失败，请检查地址和网络') from exc


class _HTMLContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks=[]; self.skip=0; self.current=[]; self.kind='paragraph'; self.level=1; self.title=[]; self.in_title=False
    def flush(self):
        text=re.sub(r'\s+',' ',' '.join(self.current)).strip()
        if text:self.blocks.append({'kind':self.kind,'text':text,'level':self.level})
        self.current=[]
    def handle_starttag(self,tag,attrs):
        if tag=='title':self.in_title=True
        if tag in ('script','style','noscript','nav','footer','form'):self.skip+=1
        if self.skip:return
        if tag in ('p','div','section','article','li','tr','figcaption','pre') or re.fullmatch(r'h[1-6]',tag):
            self.flush(); self.kind='heading' if tag.startswith('h') and len(tag)==2 else 'caption' if tag=='figcaption' else 'paragraph'
            self.level=int(tag[1]) if self.kind=='heading' else 1
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
        if tag in ('script','style','noscript','nav','footer','form') and self.skip:self.skip-=1
        if not self.skip and (tag in ('p','div','section','article','li','tr','figcaption','pre') or re.fullmatch(r'h[1-6]',tag)):self.flush()
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        elif not self.skip:self.current.append(data)


def fetch_public_document(url: str, title: str = '') -> SourceDocument:
    for _ in range(4):
        parsed, ip = public_url(url)
        port = parsed.port or (443 if parsed.scheme=='https' else 80)
        conn = http.client.HTTPSConnection(parsed.hostname,port,timeout=12) if parsed.scheme=='https' else http.client.HTTPConnection(parsed.hostname,port,timeout=12)
        try:
            sock = socket.create_connection((ip,port),timeout=12)
            conn.sock = ssl.create_default_context().wrap_socket(sock,server_hostname=parsed.hostname) if parsed.scheme=='https' else sock
            conn.request('GET',urllib.parse.urlunsplit(('', '',parsed.path or '/',parsed.query,'')),
                         headers={'User-Agent':'MindOS-Learning/1.0','Accept':'text/html,text/plain','Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:raise SearchUnavailable('网页重定向缺少地址')
                url=urllib.parse.urljoin(url,location);continue
            if response.status!=200:raise SearchUnavailable(f'网页获取失败（HTTP {response.status}）')
            kind=response.getheader('Content-Type','')
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('网页内容过大，请粘贴需要学习的部分')
            if not any(k in kind for k in ('text/html','text/plain','application/xhtml')):
                raise ValueError('网页入口仅支持 HTML 或纯文本，PDF 请下载后上传')
            text=raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
            if 'html' in kind:
                parser=_HTMLContent();parser.feed(text);parser.flush()
                blocks=parser.blocks; discovered=''.join(parser.title).strip()
            else:blocks=text_blocks(text);discovered=parsed.hostname
            return document((title or discovered or parsed.hostname)[:150],'web','direct_input',blocks,
                            url=url,parser='web-visible-text-v1',warnings=['仅提取可获取的静态文字，未运行网页脚本；图表和动态内容可能缺失'])
        except (OSError,http.client.HTTPException) as exc:
            raise SearchUnavailable('网页连接失败，请重试或直接粘贴资料') from exc
        finally:
            conn.close()
    raise SearchUnavailable('网页重定向次数过多')


class WebSearchProvider(AcquisitionProvider):
    """Search transport is injected; content acquisition remains replaceable."""
    def __init__(self, transport, provider: str):
        self.transport,self.provider=transport,provider
    def search(self, query: str) -> list[dict]:
        return self.rank_sources(self.transport.search([query]))
    def rank_sources(self, results: list[dict]) -> list[dict]:
        return sorted(results,key=lambda r:(not r.get('description'),len(r.get('title',''))<3))
    def fetch_content(self, url: str, title: str = '') -> SourceDocument:
        if self.provider!='tavily':return fetch_public_document(url,title)
        public_url(url)
        endpoint=self.transport.api_url
        if not endpoint.endswith('/search'):raise ValueError('Tavily 内容提取需要兼容 /search 与 /extract 的服务地址')
        request=urllib.request.Request(endpoint[:-len('/search')]+'/extract',
            data=json.dumps({'urls':[url],'extract_depth':'basic','format':'markdown','include_images':False}).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self.transport.api_key})
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=25) as response:
                raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('提取内容过大')
            payload=json.loads(raw)
            results=payload.get('results') if isinstance(payload,dict) else None
            if not isinstance(results,list):raise ValueError('提取服务返回格式无效')
            item=next((r for r in results if isinstance(r,dict) and r.get('url')==url),None)
            if not item or not isinstance(item.get('raw_content'),str) or not item['raw_content'].strip():
                raise SearchUnavailable('Tavily 未能提取该网页；未使用搜索摘要冒充正文')
            return document(title or urllib.parse.urlsplit(url).hostname,'web','web_search',text_blocks(item['raw_content']),
                            url=url,provider='tavily',parser='tavily-extract',warnings=['服务商提取的可用文字不一定包含网页全部内容'])
        except SearchUnavailable:raise
        except (OSError,ValueError) as exc:raise SearchUnavailable('网页内容提取失败，请检查服务地址、权限或额度') from exc
    def acquire(self, *, url: str, title: str = '', **kwargs) -> SourceDocument:
        result=self.fetch_content(url,title)
        result.origin='web_search';result.metadata['provider']=self.provider
        return result
