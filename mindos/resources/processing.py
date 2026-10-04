"""Bounded file identification, selected-page PDF extraction; never infer from filename."""
import io
from .protocol import POLICY

def identify(data):
 if not isinstance(data,bytes) or not data:raise ValueError('上传文件为空')
 if data.startswith(b'%PDF-'):kind,mime,suffix='reference','application/pdf','.pdf'
 elif data.startswith(b'\x89PNG\r\n\x1a\n'):kind,mime,suffix='image','image/png','.png'
 elif data.startswith(b'\xff\xd8\xff'):kind,mime,suffix='image','image/jpeg','.jpg'
 else:
  try:plain=data.decode('utf-8-sig')
  except UnicodeDecodeError:raise ValueError('仅支持 PNG/JPEG 图片、PDF、UTF-8 TXT/Markdown') from None
  if '\x00' in plain or any(ord(c)<32 and c not in '\n\r\t' for c in plain):raise ValueError('不是有效的文字资料')
  kind,mime,suffix='text','text/plain; charset=utf-8','.txt'
 limit=POLICY['uploads']['max_'+('pdf' if mime=='application/pdf' else kind)+'_bytes']
 if len(data)>limit:raise ValueError('文件超过此类型的大小限制')
 if kind=='image':validate_image(data,mime)
 return kind,mime,suffix

def validate_image(data,mime):
 # Decode with a maintained codec instead of treating a plausible header as a valid image.
 try:from PIL import Image
 except ImportError:raise ValueError('图片处理依赖尚未安装，请更新项目依赖后重启') from None
 import warnings
 try:
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(io.BytesIO(data)) as image:
    if image.format!=('PNG' if mime=='image/png' else 'JPEG'):raise ValueError('图片格式与实际数据不一致')
    check_pixels(*image.size)
    if getattr(image,'n_frames',1)!=1:raise ValueError('当前只支持静态 PNG/JPEG 图片')
    image.verify()
   with Image.open(io.BytesIO(data)) as image:image.load()
 except ValueError:raise
 except Exception:raise ValueError('图片损坏、尺寸过大或格式无法读取') from None

def check_pixels(w,h):
 if not w or not h or w*h>POLICY['uploads']['max_image_pixels']:raise ValueError('图片尺寸过大或无效')

def pdf_pages(data):
 from pypdf import PdfReader
 reader=PdfReader(io.BytesIO(data),strict=True)
 if reader.is_encrypted:raise ValueError('加密 PDF 无法读取')
 return reader

def extract_pdf(data,pages):
 if not isinstance(pages,list) or not 1<=len(pages)<=POLICY['uploads']['max_pdf_pages_per_extract'] or any(type(p) is not int or p<1 for p in pages) or len(set(pages))!=len(pages):raise ValueError('请选择 1–12 个不同页码')
 reader=pdf_pages(data)
 if any(p>len(reader.pages) for p in pages):raise ValueError('选中页码超出 PDF 范围')
 parts=[]
 for p in sorted(pages):
  value=(reader.pages[p-1].extract_text() or '').strip()
  if value:parts.append('第 '+str(p)+' 页\n'+value)
 result='\n\n'.join(parts)
 if not result:raise ValueError('选中页面没有可提取的文字；扫描 PDF 需要手动提供文字，当前不做 OCR')
 if len(result)>POLICY['uploads']['max_excerpt_chars']:raise ValueError('选中片段过长，请缩小页码范围')
 return result
